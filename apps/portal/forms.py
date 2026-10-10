"""Formulários das configurações da campanha (identidade e formulário público de cadastro)."""

from __future__ import annotations

import re

from django import forms

from apps.core.constants import DEFAULT_CONSENT_TEXT, UF_CHOICES, Office, parse_form_config
from apps.core.forms import StyledFormMixin

from .settings_rules import (
    FORM_FIELD_GROUPS,
    FORM_FIELD_MODE_CHOICES,
    HEX_COLOR_RE,
    LIMITS,
    LOGO_DATA_URL_MAX_CHARS,
    LogoError,
    check_logo_data_url,
)

LOGO_ACTIONS = ("keep", "remove", "replace")


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_newlines(value: str) -> str:
    return (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


class IdentityForm(StyledFormMixin, forms.Form):
    """Cartão "Identidade da campanha". Os dados saem como atributos de Campaign (veja `campaign_values`)."""

    candidate_name = forms.CharField(
        label="Nome completo do candidato",
        min_length=3,
        max_length=LIMITS["candidate_name"],
        error_messages={"min_length": "Informe o nome completo do candidato."},
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    ballot_name = forms.CharField(
        label="Nome de urna",
        min_length=2,
        max_length=LIMITS["ballot_name"],
        help_text="Como aparece na urna e nas mensagens (variável {{candidato}}).",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    ballot_number = forms.CharField(
        label="Número",
        required=False,
        max_length=10,
        help_text="De 2 a 5 dígitos.",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "Ex.: 12345", "autocomplete": "off"}),
    )
    party = forms.CharField(
        label="Partido / federação",
        required=False,
        max_length=LIMITS["party"],
        widget=forms.TextInput(attrs={"placeholder": "Ex.: PXX", "autocomplete": "off"}),
    )
    office = forms.ChoiceField(
        label="Cargo disputado",
        choices=Office.choices,
        error_messages={"invalid_choice": "Escolha o cargo disputado."},
    )
    election_year = forms.IntegerField(
        label="Ano da eleição",
        min_value=LIMITS["election_year_min"],
        max_value=LIMITS["election_year_max"],
        error_messages={"invalid": "Ano inválido.", "min_value": "Ano inválido.", "max_value": "Ano inválido."},
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    city = forms.CharField(
        label="Cidade",
        required=False,
        max_length=LIMITS["city"],
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Campinas"}),
    )
    state = forms.ChoiceField(
        label="UF",
        required=False,
        choices=[("", "Selecione"), *UF_CHOICES],
        error_messages={"invalid_choice": "Escolha uma UF válida."},
    )
    voter_goal = forms.IntegerField(
        label="Meta de cadastros",
        required=False,
        min_value=1,
        max_value=LIMITS["voter_goal_max"],
        help_text="Total de eleitores que a campanha pretende cadastrar.",
        error_messages={
            "invalid": "Informe uma meta entre 1 e 10.000.000.",
            "min_value": "Informe uma meta entre 1 e 10.000.000.",
            "max_value": "Informe uma meta entre 1 e 10.000.000.",
        },
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "Ex.: 5000"}),
    )
    primary_color = forms.CharField(
        label="Cor principal",
        max_length=7,
        error_messages={
            "required": "Informe a cor principal.",
            "max_length": "Use o formato hexadecimal #RRGGBB (ex.: #4f46e5).",
        },
        widget=forms.TextInput(
            attrs={
                "placeholder": "#4f46e5",
                "autocomplete": "off",
                "spellcheck": "false",
                "pattern": "#[0-9a-fA-F]{6}",
                "title": "Use o formato hexadecimal #RRGGBB (ex.: #4f46e5)",
            }
        ),
    )
    # O logo é redimensionado no navegador e chega como data URL; é revalidado aqui (veja `clean`)
    logo_action = forms.ChoiceField(
        required=False, choices=[(a, a) for a in LOGO_ACTIONS], widget=forms.HiddenInput
    )
    logo_data = forms.CharField(
        required=False,
        strip=True,
        max_length=LOGO_DATA_URL_MAX_CHARS,
        error_messages={"max_length": "A imagem deve ter no máximo 300 KB."},
        widget=forms.HiddenInput,
    )

    def clean_candidate_name(self):
        return _single_line(self.cleaned_data["candidate_name"])

    def clean_ballot_name(self):
        value = _single_line(self.cleaned_data["ballot_name"])
        if len(value) < 2:
            raise forms.ValidationError("Informe o nome de urna.")
        return value

    def clean_ballot_number(self):
        value = (self.cleaned_data.get("ballot_number") or "").strip()
        if value and not re.fullmatch(r"\d{2,5}", value):
            raise forms.ValidationError("O número de urna tem de 2 a 5 dígitos.")
        return value

    def clean_party(self):
        return _single_line(self.cleaned_data.get("party") or "")

    def clean_city(self):
        return _single_line(self.cleaned_data.get("city") or "")

    def clean_state(self):
        return (self.cleaned_data.get("state") or "").upper()

    def clean_primary_color(self):
        value = (self.cleaned_data["primary_color"] or "").strip()
        if not HEX_COLOR_RE.fullmatch(value):
            raise forms.ValidationError("Use o formato hexadecimal #RRGGBB (ex.: #4f46e5).")
        return value.lower()

    def clean_logo_action(self):
        return self.cleaned_data.get("logo_action") or "keep"

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("logo_action") or "keep"
        data = cleaned.get("logo_data") or ""
        if action == "replace":
            if "logo_data" not in self.errors:
                try:
                    check_logo_data_url(data)
                except LogoError as exc:
                    self.add_error("logo_data", str(exc))
        else:
            cleaned["logo_data"] = ""  # o servidor ignora qualquer imagem enviada sem a ação "replace"
        return cleaned

    @staticmethod
    def initial_from(campaign) -> dict:
        return {
            "candidate_name": campaign.candidate_name,
            "ballot_name": campaign.ballot_name,
            "ballot_number": campaign.ballot_number,
            "party": campaign.party,
            "office": campaign.office,
            "election_year": campaign.election_year,
            "city": campaign.city,
            "state": campaign.state,
            "voter_goal": campaign.voter_goal,
            "primary_color": campaign.primary_color,
            "logo_action": "keep",
        }

    def campaign_values(self, campaign) -> dict:
        """Novos valores dos campos de Campaign deste cartão (já validados)."""
        data = self.cleaned_data
        action = data.get("logo_action") or "keep"
        if action == "replace":
            logo_url = data["logo_data"]
        elif action == "remove":
            logo_url = ""
        else:
            logo_url = campaign.logo_url
        return {
            "candidate_name": data["candidate_name"],
            "ballot_name": data["ballot_name"],
            "ballot_number": data["ballot_number"],
            "party": data["party"],
            "office": data["office"],
            "city": data["city"],
            "state": data["state"],
            "election_year": data["election_year"],
            "voter_goal": data["voter_goal"],
            "primary_color": data["primary_color"],
            "logo_url": logo_url,
        }


def _mode_field(label: str) -> forms.ChoiceField:
    return forms.ChoiceField(
        label=label,
        choices=FORM_FIELD_MODE_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "peer sr-only"}),
        error_messages={"invalid_choice": "Escolha oculto, opcional ou obrigatório."},
    )


class PublicFormSettingsForm(StyledFormMixin, forms.Form):
    """Cartão "Formulário público de cadastro"."""

    form_title = forms.CharField(
        label="Título",
        required=False,
        max_length=LIMITS["form_title"],
        help_text="Opcional. Em branco: \"Faça parte da campanha de <nome de urna>\".",
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Faça parte da campanha de nosso candidato"}),
    )
    form_message = forms.CharField(
        label="Mensagem de boas-vindas",
        required=False,
        max_length=LIMITS["form_message"],
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Ex.: Cadastre-se para receber novidades da campanha e participar dos nossos encontros no seu bairro.",
            }
        ),
    )
    consent_text = forms.CharField(
        label="Texto de consentimento (LGPD)",
        required=False,
        max_length=LIMITS["consent_text_max"],
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": DEFAULT_CONSENT_TEXT}),
    )
    privacy_contact = forms.CharField(
        label="Contato do encarregado / controlador de dados",
        required=False,
        max_length=LIMITS["privacy_contact"],
        help_text="Exibido na política de privacidade do formulário para o eleitor pedir acesso, correção ou exclusão dos dados.",
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Maria Souza · privacidade@suacampanha.com.br"}),
    )

    # Um seletor Oculto/Opcional/Obrigatório por grupo (chaves de Campaign.form_config)
    config_email = _mode_field("E-mail")
    config_birth_date = _mode_field("Data de nascimento")
    config_gender = _mode_field("Gênero")
    config_address = _mode_field("Endereço")
    config_electoral = _mode_field("Zona e seção eleitoral")

    def clean_form_title(self):
        return _single_line(self.cleaned_data.get("form_title") or "")

    def clean_form_message(self):
        return _normalize_newlines(self.cleaned_data.get("form_message") or "")

    def clean_consent_text(self):
        value = _normalize_newlines(self.cleaned_data.get("consent_text") or "")
        if value == DEFAULT_CONSENT_TEXT:
            return ""  # igual ao padrão: segue o padrão da plataforma
        if value and len(value) < LIMITS["consent_text_min"]:
            raise forms.ValidationError(
                f"O texto de consentimento deve ter pelo menos {LIMITS['consent_text_min']} caracteres "
                "(ou deixe em branco para usar o padrão)."
            )
        return value

    def clean_privacy_contact(self):
        return _single_line(self.cleaned_data.get("privacy_contact") or "")

    @staticmethod
    def initial_from(campaign) -> dict:
        config = parse_form_config(campaign.form_config)
        return {
            "form_title": campaign.form_title,
            "form_message": campaign.form_message,
            "consent_text": campaign.consent_text,
            "privacy_contact": campaign.privacy_contact,
            **{f"config_{key}": mode for key, mode in config.items()},
        }

    def mode_rows(self) -> list[dict]:
        """Linhas do seletor de modos para o template: grupo + campo (BoundField) do formulário."""
        return [{**group, "field": self[f"config_{group['key']}"]} for group in FORM_FIELD_GROUPS]

    def campaign_values(self) -> dict:
        data = self.cleaned_data
        return {
            "form_title": data["form_title"],
            "form_message": data["form_message"],
            "form_config": {group["key"]: data[f"config_{group['key']}"] for group in FORM_FIELD_GROUPS},
            "consent_text": data["consent_text"],
            "privacy_contact": data["privacy_contact"],
        }
