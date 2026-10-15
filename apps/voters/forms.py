"""Formulários de apoiador: cadastro público (link/QR), cadastro manual no painel, edição e troca de responsável.

Os campos pessoais/endereço/título são comuns (`VoterDataForm`); o modo de cada grupo vem da configuração da campanha
(`Campaign.form_config`: hidden | optional | required). No painel todos os grupos são opcionais.
"""

from __future__ import annotations

import datetime as dt

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.core.access import team_scope
from apps.core.constants import (
    DEFAULT_FORM_CONFIG,
    UF_CHOICES,
    Gender,
    Role,
    SupportLevel,
    VoterSource,
    label_of,
    parse_form_config,
)
from apps.core.forms import PhoneField, StyledFormMixin
from apps.core.utils import age_from, parse_tags, serialize_tags, title_case
from apps.geo.cep import format_cep, normalize_cep

from .utils import (
    MAX_VOTER_AGE,
    MIN_VOTER_AGE,
    collapse_spaces,
    has_letter,
    is_voter_age,
    normalize_digits_field,
    parse_birth_date_input,
    smart_case,
)

# Configuração do painel: todos os grupos visíveis e opcionais
PANEL_FORM_CONFIG = {key: "optional" for key in DEFAULT_FORM_CONFIG}

# Grupo da configuração → campos do formulário
CONFIG_GROUPS = {
    "email": ("email",),
    "birth_date": ("birth_date",),
    "gender": ("gender",),
    "address": ("cep", "street", "number", "complement", "neighborhood", "city", "state"),
    "electoral": ("electoral_zone", "electoral_section"),
}
# Campos exigidos quando o grupo está em modo "required" (rua, número e complemento do endereço: veja docstring do módulo)
REQUIRED_IN_GROUP = {
    "email": ("email",),
    "birth_date": ("birth_date",),
    "gender": ("gender",),
    "address": ("cep", "street", "number", "neighborhood", "city", "state"),
    "electoral": ("electoral_zone", "electoral_section"),
}

# Campos do model Voter preenchidos pelos formulários de dados pessoais
VOTER_DATA_KEYS = (
    "name",
    "phone",
    "email",
    "birth_date",
    "gender",
    "cep",
    "street",
    "number",
    "complement",
    "neighborhood",
    "city",
    "state",
    "electoral_zone",
    "electoral_section",
)


def voter_data_from_cleaned(cleaned: dict) -> dict:
    """Dados do apoiador a gravar (campos ocultos/ausentes viram vazio — nunca confiamos no que o cliente enviar)."""
    data = {key: cleaned.get(key) or "" for key in VOTER_DATA_KEYS}
    data["birth_date"] = cleaned.get("birth_date") or None
    return data


def voter_initial(voter) -> dict:
    """Valores iniciais do formulário de edição a partir de um Voter."""
    initial = {key: getattr(voter, key) for key in VOTER_DATA_KEYS}
    initial.update(
        support_level=voter.support_level,
        tags=", ".join(parse_tags(voter.tags)),
        notes=voter.notes,
        cep=format_cep(voter.cep),  # guardado só com dígitos; a máscara só age ao digitar, então formatamos aqui
    )
    return initial


class BirthDateField(forms.DateField):
    """Data de nascimento digitada como dd/mm/aaaa (também aceita aaaa-mm-dd, dd-mm-aaaa, dd.mm.aaaa, ddmmaaaa)."""

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        parsed = parse_birth_date_input(str(value))
        if parsed is None:
            raise ValidationError("Data inválida. Use o formato dd/mm/aaaa.", code="invalid")
        return parsed


_CEP_TARGET = "street:#id_street,neighborhood:#id_neighborhood,city:#id_city,state:#id_state"


class VoterDataForm(StyledFormMixin, forms.Form):
    """Dados pessoais, endereço e título eleitoral. `config` define quais grupos aparecem e quais são obrigatórios."""

    name = forms.CharField(
        label="Nome completo",
        min_length=3,
        max_length=120,
        error_messages={"required": "Informe o nome completo.", "min_length": "Informe o nome completo."},
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Seu nome completo"}),
    )
    phone = PhoneField(
        label="WhatsApp",
        error_messages={"required": "Informe o WhatsApp com DDD."},
        help_text="Com DDD, por exemplo (11) 98765-4321.",
    )
    email = forms.EmailField(
        label="E-mail",
        required=False,
        max_length=160,
        error_messages={"required": "Informe o e-mail.", "invalid": "E-mail inválido. Confira o endereço."},
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "voce@exemplo.com"}),
    )
    birth_date = BirthDateField(
        label="Data de nascimento",
        required=False,
        error_messages={"required": "Informe a data de nascimento."},
        widget=forms.DateInput(
            format="%d/%m/%Y",
            attrs={
                "placeholder": "dd/mm/aaaa",
                "inputmode": "numeric",
                "autocomplete": "bday",
                "maxlength": "10",
                "data-mask": "date",
            },
        ),
    )
    gender = forms.ChoiceField(
        label="Gênero",
        required=False,
        choices=[("", "Selecione"), *Gender.choices],
        error_messages={"required": "Selecione uma opção.", "invalid_choice": "Opção inválida."},
    )
    cep = forms.CharField(
        label="CEP",
        required=False,
        max_length=9,
        error_messages={"required": "Informe o CEP."},
        help_text="Digite o CEP e preenchemos o endereço para você.",
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "postal-code",
                "placeholder": "00000-000",
                "data-mask": "cep",
                "data-cep-lookup": True,
                "data-cep-target": _CEP_TARGET,
                "data-cep-status": "#cep-status",
            }
        ),
    )
    street = forms.CharField(
        label="Logradouro",
        required=False,
        max_length=160,
        error_messages={"required": "Informe o logradouro."},
        widget=forms.TextInput(attrs={"autocomplete": "address-line1", "placeholder": "Rua, avenida..."}),
    )
    number = forms.CharField(
        label="Número",
        required=False,
        max_length=20,
        error_messages={"required": "Informe o número (ou s/n)."},
        widget=forms.TextInput(attrs={"placeholder": "Número ou s/n", "autocomplete": "off"}),
    )
    complement = forms.CharField(
        label="Complemento",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "Apto, bloco..."}),
    )
    neighborhood = forms.CharField(
        label="Bairro",
        required=False,
        max_length=100,
        error_messages={"required": "Informe o bairro."},
        widget=forms.TextInput(attrs={"autocomplete": "address-level3"}),
    )
    city = forms.CharField(
        label="Cidade",
        required=False,
        max_length=100,
        error_messages={"required": "Informe a cidade."},
        widget=forms.TextInput(attrs={"autocomplete": "address-level2"}),
    )
    state = forms.ChoiceField(
        label="UF",
        required=False,
        choices=[("", "UF"), *UF_CHOICES],
        error_messages={"required": "Informe a UF.", "invalid_choice": "UF inválida."},
    )
    electoral_zone = forms.CharField(
        label="Zona eleitoral",
        required=False,
        max_length=4,
        error_messages={"required": "Informe a zona eleitoral."},
        widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "Ex.: 25", "autocomplete": "off"}),
    )
    electoral_section = forms.CharField(
        label="Seção eleitoral",
        required=False,
        max_length=5,
        error_messages={"required": "Informe a seção eleitoral."},
        widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "Ex.: 120", "autocomplete": "off"}),
    )

    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = dict(PANEL_FORM_CONFIG) if config is None else parse_form_config(config)
        self._apply_config()

    def _apply_config(self) -> None:
        for group, names in CONFIG_GROUPS.items():
            mode = self.config[group]
            for name in names:
                if mode == "hidden":
                    self.fields.pop(name, None)
                elif mode == "required" and name in REQUIRED_IN_GROUP[group]:
                    self.fields[name].required = True
                    self.fields[name].widget.attrs["required"] = "required"

    # Para os templates: quais grupos existem neste formulário
    @property
    def show_email(self) -> bool:
        return "email" in self.fields

    @property
    def show_birth_date(self) -> bool:
        return "birth_date" in self.fields

    @property
    def show_gender(self) -> bool:
        return "gender" in self.fields

    @property
    def show_address(self) -> bool:
        return "cep" in self.fields

    @property
    def show_electoral(self) -> bool:
        return "electoral_zone" in self.fields

    # --- limpeza dos campos ----------------------------------------------------------------------
    def clean_name(self):
        value = collapse_spaces(self.cleaned_data.get("name"))
        if len(value) < 3 or not has_letter(value):
            raise ValidationError("Informe o nome completo.")
        return title_case(value)

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean_birth_date(self):
        value = self.cleaned_data.get("birth_date")
        if value is None:
            return None
        if not is_voter_age(age_from(value, timezone.localdate())):
            raise ValidationError(f"A idade deve estar entre {MIN_VOTER_AGE} e {MAX_VOTER_AGE} anos.")
        return value

    def clean_cep(self):
        raw = (self.cleaned_data.get("cep") or "").strip()
        if not raw:
            return ""
        cep = normalize_cep(raw)
        if cep is None:
            raise ValidationError("CEP inválido. Informe os 8 dígitos.")
        return cep

    def clean_street(self):
        return smart_case(self.cleaned_data.get("street"))

    def clean_number(self):
        return collapse_spaces(self.cleaned_data.get("number"))

    def clean_complement(self):
        return collapse_spaces(self.cleaned_data.get("complement"))

    def clean_neighborhood(self):
        return smart_case(self.cleaned_data.get("neighborhood"))

    def clean_city(self):
        return smart_case(self.cleaned_data.get("city"))

    def clean_electoral_zone(self):
        raw = (self.cleaned_data.get("electoral_zone") or "").strip()
        if not raw:
            return ""
        value = normalize_digits_field(raw, 4)
        if value is None:
            raise ValidationError("Zona eleitoral inválida. Use apenas números (até 4 dígitos).")
        return value

    def clean_electoral_section(self):
        raw = (self.cleaned_data.get("electoral_section") or "").strip()
        if not raw:
            return ""
        value = normalize_digits_field(raw, 5)
        if value is None:
            raise ValidationError("Seção eleitoral inválida. Use apenas números (até 5 dígitos).")
        return value


class PublicRegistrationForm(VoterDataForm):
    """Formulário público (/c/<code>/). Consentimento LGPD obrigatório e opt-in de WhatsApp separado."""

    consent = forms.BooleanField(
        required=True,
        error_messages={"required": "Para concluir o cadastro, autorize o uso dos seus dados."},
        widget=forms.CheckboxInput(attrs={"required": "required"}),
    )
    whatsapp_opt_in = forms.BooleanField(required=False)
    source = forms.CharField(required=False, widget=forms.HiddenInput)
    # Honeypot: pessoas não veem nem preenchem; robôs costumam preencher tudo
    website = forms.CharField(
        required=False,
        label="Site",
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}),
    )

    def __init__(self, *args, config=None, **kwargs):
        # Sem configuração explícita vale o padrão da campanha (endereço obrigatório), nunca o modo "tudo opcional" do painel
        super().__init__(*args, config=parse_form_config(config), **kwargs)

    def clean_source(self):
        value = (self.cleaned_data.get("source") or "").strip().upper()
        return value if value in (VoterSource.LINK, VoterSource.QRCODE) else VoterSource.LINK.value


def _registrar_label(user) -> str:
    return f"{user.name} · {label_of(Role, user.role)}"


class VoterPanelForm(VoterDataForm):
    """Campos extras do painel: classificação do apoiador."""

    support_level = forms.ChoiceField(
        label="Nível de apoio",
        required=False,
        choices=[("", "Não classificado"), *SupportLevel.choices],
        error_messages={"invalid_choice": "Nível de apoio inválido."},
    )
    tags = forms.CharField(
        label="Tags",
        required=False,
        max_length=300,
        help_text="Separe por vírgulas. Ex.: saúde, jovem, líder comunitário.",
        widget=forms.TextInput(attrs={"placeholder": "saúde, jovem"}),
    )
    notes = forms.CharField(
        label="Observações",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, campaign_id=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campaign_id = campaign_id
        self.instance = instance

    def clean_tags(self):
        return serialize_tags(self.cleaned_data.get("tags") or "") or ""

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").replace("\r\n", "\n").strip()

    def clean_phone(self):
        phone = self.cleaned_data.get("phone")
        if phone:
            from .models import Voter

            qs = Voter.objects.filter(campaign_id=self.campaign_id, phone=phone)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError("Telefone já cadastrado na campanha.", code="duplicate")
        return phone


class VoterCreateForm(VoterPanelForm):
    """Cadastro manual. `registered_by` só existe para ADMIN/COORDENADOR (CABO sempre cadastra para si)."""

    registered_by = forms.ModelChoiceField(
        label="Cadastrado por",
        queryset=User.objects.none(),
        required=False,
        empty_label=None,
        help_text="O apoiador fica vinculado a este membro da equipe.",
    )
    consent = forms.BooleanField(
        required=True,
        label="O apoiador autorizou o uso dos dados (LGPD)",
        error_messages={"required": "Confirme que o apoiador autorizou o uso dos dados."},
    )
    whatsapp_opt_in = forms.BooleanField(
        required=False, label="O apoiador autorizou receber mensagens no WhatsApp"
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, campaign_id=user.campaign_id, **kwargs)
        self.user = user
        if user.role == Role.CABO:
            del self.fields["registered_by"]
        else:
            field = self.fields["registered_by"]
            field.queryset = team_scope(user).filter(is_active=True).order_by("name")
            field.initial = user.pk
            field.label_from_instance = _registrar_label

    def clean_registered_by(self):
        return self.cleaned_data.get("registered_by") or self.user


class VoterEditForm(VoterPanelForm):
    """Edição no painel (consentimento e "cadastrado por" têm ações próprias)."""

    def __init__(self, *args, voter, **kwargs):
        super().__init__(*args, campaign_id=voter.campaign_id, instance=voter, **kwargs)


class ChangeRegistrarForm(StyledFormMixin, forms.Form):
    """Troca de "cadastrado por" (somente ADMIN): o novo responsável precisa ser da MESMA campanha e estar ativo."""

    registered_by = forms.ModelChoiceField(
        queryset=User.objects.none(), empty_label="Selecione um membro da equipe", label="Cadastrado por"
    )

    def __init__(self, *args, campaign_id, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["registered_by"]
        field.queryset = User.objects.filter(campaign_id=campaign_id, is_active=True).exclude(role=Role.SUPER_ADMIN).order_by("name")
        field.label_from_instance = _registrar_label
        field.error_messages["invalid_choice"] = "Selecione um membro da equipe."


class ImportForm(StyledFormMixin, forms.Form):
    """Envio final da importação. O CSV e o mapeamento chegam como texto e são revalidados no servidor."""

    csv_text = forms.CharField(required=False, widget=forms.HiddenInput)
    mapping = forms.CharField(required=False, widget=forms.HiddenInput)
    has_header = forms.BooleanField(required=False)
    declaration = forms.BooleanField(
        required=True,
        error_messages={"required": "Confirme a declaração de consentimento (LGPD) para importar."},
    )
    whatsapp_opt_in = forms.BooleanField(required=False)
    registered_by = forms.ModelChoiceField(queryset=User.objects.none(), required=False, empty_label=None)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user.role == Role.CABO:
            del self.fields["registered_by"]
        else:
            field = self.fields["registered_by"]
            field.queryset = team_scope(user).filter(is_active=True).order_by("name")
            field.initial = user.pk
            field.label_from_instance = _registrar_label

    def clean_registered_by(self):
        return self.cleaned_data.get("registered_by") or self.user
