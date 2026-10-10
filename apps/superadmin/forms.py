"""Formulários do super admin (campanha, contas, exclusão e filtro de auditoria)."""

from __future__ import annotations

import re

from django import forms
from django.contrib.auth import password_validation
from django.utils import timezone

from apps.accounts.services import email_in_use
from apps.auditlog.actions import AUDIT_ACTIONS
from apps.campaigns.models import Campaign
from apps.core.constants import UF_CHOICES, CampaignStatus, Office
from apps.core.forms import PhoneField, StyledFormMixin

DEFAULT_PRIMARY_COLOR = "#4f46e5"
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL_TAKEN = "Este e-mail já está cadastrado no E-Find. Use outro."
# Valor do filtro de campanha para eventos sem campanha (ações da plataforma)
PLATFORM_SCOPE = "plataforma"

# Dígitos do número de urna por cargo (Código Eleitoral): majoritários 2, senador 3, dep. federal 4,
# dep. estadual/distrital e vereador 5. Cargos fora da tabela aceitam de 2 a 5 dígitos.
BALLOT_NUMBER_LENGTH = {
    Office.PREFEITO: 2,
    Office.VICE_PREFEITO: 2,
    Office.GOVERNADOR: 2,
    Office.PRESIDENTE: 2,
    Office.SENADOR: 3,
    Office.DEPUTADO_FEDERAL: 4,
    Office.DEPUTADO_ESTADUAL: 5,
    Office.DEPUTADO_DISTRITAL: 5,
    Office.VEREADOR: 5,
}


def expected_ballot_number_length(office: str) -> int | None:
    return BALLOT_NUMBER_LENGTH.get(office)


class CampaignForm(StyledFormMixin, forms.ModelForm):
    """Dados do candidato / campanha (criação e edição)."""

    office = forms.ChoiceField(label="Cargo", choices=[("", "Selecione o cargo"), *Office.choices])
    state = forms.ChoiceField(label="UF", required=False, choices=[("", "Selecione"), *UF_CHOICES])
    election_year = forms.IntegerField(
        label="Ano da eleição",
        min_value=2000,
        max_value=2100,
        error_messages={"invalid": "Informe um ano válido.", "min_value": "Informe um ano válido.", "max_value": "Informe um ano válido."},
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    primary_color = forms.CharField(
        label="Cor principal",
        required=False,
        max_length=7,
        widget=forms.TextInput(attrs={"type": "color", "class": "h-10 w-full cursor-pointer p-1 sm:w-24"}),
        help_text="Usada na identidade da campanha no painel.",
    )
    voter_goal = forms.IntegerField(
        label="Meta de cadastros",
        required=False,
        min_value=1,
        max_value=100_000_000,
        error_messages={"invalid": "Informe um número inteiro.", "min_value": "A meta deve ser maior que zero.", "max_value": "Meta muito alta."},
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "Ex.: 5000"}),
    )

    class Meta:
        model = Campaign
        fields = [
            "candidate_name",
            "ballot_name",
            "ballot_number",
            "party",
            "office",
            "city",
            "state",
            "election_year",
            "primary_color",
            "voter_goal",
        ]
        labels = {
            "candidate_name": "Nome do candidato",
            "ballot_name": "Nome de urna",
            "ballot_number": "Número de urna",
            "party": "Partido",
            "city": "Cidade",
        }
        widgets = {
            "ballot_number": forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "Ex.: 12345"}),
            "party": forms.TextInput(attrs={"placeholder": "Sigla, ex.: PSD"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["candidate_name"].help_text = "Nome completo, como no registro de candidatura."
        self.fields["ballot_name"].help_text = "Usado no painel e para gerar o identificador da campanha."
        if self.instance._state.adding and not self.is_bound:
            self.initial["election_year"] = timezone.localdate().year
            self.initial["primary_color"] = DEFAULT_PRIMARY_COLOR

    def clean_candidate_name(self):
        value = (self.cleaned_data.get("candidate_name") or "").strip()
        if len(value) < 3:
            raise forms.ValidationError("Informe o nome completo do candidato.")
        return value

    def clean_ballot_name(self):
        value = (self.cleaned_data.get("ballot_name") or "").strip()
        if len(value) < 2:
            raise forms.ValidationError("Informe o nome de urna.")
        return value

    def clean_ballot_number(self):
        value = (self.cleaned_data.get("ballot_number") or "").strip()
        if value and not re.fullmatch(r"\d{2,5}", value):
            raise forms.ValidationError("Use de 2 a 5 dígitos.")
        return value

    def clean_party(self):
        return (self.cleaned_data.get("party") or "").strip()

    def clean_city(self):
        return (self.cleaned_data.get("city") or "").strip()

    def clean_primary_color(self):
        value = (self.cleaned_data.get("primary_color") or "").strip()
        if not value:
            return DEFAULT_PRIMARY_COLOR
        if not COLOR_RE.fullmatch(value):
            raise forms.ValidationError("Cor inválida (use o formato #RRGGBB).")
        return value.lower()

    def clean(self):
        data = super().clean()
        number = data.get("ballot_number")
        office = data.get("office")
        expected = expected_ballot_number_length(office) if office else None
        if number and expected and len(number) != expected:
            self.add_error("ballot_number", f"Para este cargo o número de urna tem {expected} dígitos.")
        return data


class AccountForm(StyledFormMixin, forms.Form):
    """Conta criada pelo super admin (administrador de campanha ou super admin). Senha vazia = gerar provisória."""

    name = forms.CharField(label="Nome completo", min_length=3, max_length=160)
    email = forms.EmailField(label="E-mail", max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "off"}))
    phone = PhoneField(label="Telefone / WhatsApp", required=False)
    password = forms.CharField(
        label="Senha",
        required=False,
        max_length=128,
        help_text="Opcional: deixe em branco para gerar uma senha provisória (exibida uma única vez).",
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )

    def clean_name(self):
        value = (self.cleaned_data.get("name") or "").strip()
        if len(value) < 3:
            raise forms.ValidationError("Informe o nome completo.")
        return value

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip().lower()
        if email_in_use(value):
            raise forms.ValidationError(EMAIL_TAKEN)
        return value

    def clean_password(self):
        value = self.cleaned_data.get("password") or ""
        if not value:
            return ""
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise forms.ValidationError("A senha deve conter letras e números.")
        password_validation.validate_password(value)
        return value


class DeleteCampaignForm(StyledFormMixin, forms.Form):
    """Exclusão definitiva: exige digitar o identificador (slug) da campanha."""

    confirm_slug = forms.CharField(
        label="Identificador da campanha",
        max_length=80,
        error_messages={"required": "Digite o identificador da campanha."},
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "off", "spellcheck": "false"}),
    )

    def __init__(self, *args, campaign: Campaign | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campaign = campaign

    def clean_confirm_slug(self):
        value = (self.cleaned_data.get("confirm_slug") or "").strip()
        if self.campaign is None or value != self.campaign.slug:
            raise forms.ValidationError("O identificador digitado não confere.")
        return value


class AuditFilterForm(StyledFormMixin, forms.Form):
    """Filtros da auditoria da plataforma (GET)."""

    campaign = forms.ChoiceField(label="Campanha", required=False)
    action = forms.ChoiceField(label="Ação", required=False)
    start = forms.DateField(
        label="De", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    end = forms.DateField(
        label="Até", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campaigns = Campaign.objects.order_by("ballot_name").values_list("pk", "ballot_name", "ballot_number")
        self.fields["campaign"].choices = [
            ("", "Todas as campanhas"),
            (PLATFORM_SCOPE, "Plataforma (sem campanha)"),
            *[(str(pk), f"{name} · {number}" if number else name) for pk, name, number in campaigns],
        ]
        self.fields["action"].choices = [
            ("", "Todas as ações"),
            *sorted(AUDIT_ACTIONS.items(), key=lambda item: item[1].lower()),
        ]

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and start > end:  # datas invertidas: troca em vez de dar erro
            data["start"], data["end"] = end, start
        return data


class CampaignListForm(StyledFormMixin, forms.Form):
    """Busca e filtro de status da lista de campanhas (GET)."""

    q = forms.CharField(label="Buscar", required=False, max_length=100, widget=forms.TextInput(attrs={"type": "search"}))
    status = forms.ChoiceField(
        label="Status", required=False, choices=[("", "Todos os status"), *CampaignStatus.choices]
    )
