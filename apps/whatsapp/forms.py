"""Formulários das conexões de WhatsApp. O formulário de conexão é montado a partir dos campos de cada
`ProviderDefinition` (campos `cred_<nome>`); segredos em branco mantêm o valor salvo e nunca são devolvidos ao navegador."""

from __future__ import annotations

import re
from collections.abc import Mapping

from django import forms

from apps.core.crypto import mask_secret
from apps.core.forms import PhoneField, StyledFormMixin, style_widget

from .credentials import DEFAULT_CREDENTIALS, CredentialError, validate_credential
from .types import ProviderDefinition, ProviderField

CRED_PREFIX = "cred_"
CLEAR_PREFIX = "clear_"
DEFAULT_RATE_PER_MINUTE = 20
MAX_RATE_PER_MINUTE = 600


class ConnectionForm(StyledFormMixin, forms.Form):
    """Dados de uma conexão (nova ou existente) para um provedor fixo."""

    name = forms.CharField(
        label="Nome da conexão",
        min_length=2,
        max_length=80,
        help_text="Só para você identificar, ex.: “WhatsApp oficial da campanha”.",
        widget=forms.TextInput(attrs={"placeholder": "WhatsApp oficial da campanha"}),
    )
    phone_number = forms.CharField(
        label="Número exibido",
        required=False,
        max_length=30,
        help_text="Opcional. O número de WhatsApp da campanha, só para exibição (ex.: +55 11 98765-4321).",
        widget=forms.TextInput(attrs={"inputmode": "tel", "placeholder": "+55 11 98765-4321"}),
    )
    rate_per_minute = forms.IntegerField(
        label="Mensagens por minuto",
        min_value=1,
        max_value=MAX_RATE_PER_MINUTE,
        initial=DEFAULT_RATE_PER_MINUTE,
        error_messages={"invalid": "Informe um número inteiro."},
        widget=forms.NumberInput(attrs={"min": 1, "max": MAX_RATE_PER_MINUTE, "inputmode": "numeric"}),
    )

    def __init__(self, *args, definition: ProviderDefinition, existing: Mapping[str, str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.definition = definition
        self.is_edit = existing is not None
        self.existing: dict[str, str] = dict(existing or {})
        self.credentials: dict[str, str] = {}
        self.changed_fields: list[str] = []

        for spec in definition.fields:
            attrs = {"autocomplete": "off", "autocapitalize": "off", "spellcheck": "false"}
            if spec.placeholder:
                attrs["placeholder"] = spec.placeholder
            if spec.secret:
                widget: forms.Widget = forms.PasswordInput(render_value=False, attrs=attrs)
            elif spec.type == "url":
                widget = forms.URLInput(attrs=attrs)
            else:
                widget = forms.TextInput(attrs=attrs)
            kept = bool(spec.secret and self.existing.get(spec.name))
            if spec.required and not kept:
                widget.attrs["required"] = "required"
            if spec.secret:
                initial = None  # segredos nunca são pré-preenchidos
            elif self.is_edit:
                initial = self.existing.get(spec.name)
            else:
                initial = DEFAULT_CREDENTIALS.get(spec.name)
            self.fields[CRED_PREFIX + spec.name] = forms.CharField(
                label=spec.label, required=False, help_text=spec.help, initial=initial, widget=widget
            )
            if self.is_edit and spec.secret and not spec.required and kept:
                self.fields[CLEAR_PREFIX + spec.name] = forms.BooleanField(
                    label="Remover o valor salvo", required=False, widget=forms.CheckboxInput
                )

        for field in self.fields.values():  # estilo (idempotente) dos campos adicionados dinamicamente
            style_widget(field.widget)

    # ------------------------------------------------------------------------------ Template

    @property
    def credential_rows(self) -> list[dict]:
        """Uma linha por campo do provedor, para renderizar manualmente (rótulo, controle, máscara, dica)."""
        rows = []
        for spec in self.definition.fields:
            kept = self.existing.get(spec.name, "") if spec.secret else ""
            rows.append(
                {
                    "spec": spec,
                    "field": self[CRED_PREFIX + spec.name],
                    "masked": mask_secret(kept) if kept else "",
                    "clear": self[CLEAR_PREFIX + spec.name] if (CLEAR_PREFIX + spec.name) in self.fields else None,
                }
            )
        return rows

    # ------------------------------------------------------------------------------ Validação

    def clean_phone_number(self):
        value = (self.cleaned_data.get("phone_number") or "").strip()
        if value and not re.fullmatch(r"[\d\s()+.\-]{5,30}", value):
            raise forms.ValidationError("Use apenas números, espaços e os símbolos + - ( ).")
        return value

    def clean(self):
        cleaned = super().clean()
        credentials: dict[str, str] = {}
        for spec in self.definition.fields:
            self._clean_credential(spec, cleaned, credentials)
        self.credentials = credentials
        self.changed_fields = [
            spec.name for spec in self.definition.fields if credentials.get(spec.name, "") != self.existing.get(spec.name, "")
        ]
        return cleaned

    def _clean_credential(self, spec: ProviderField, cleaned: dict, credentials: dict[str, str]) -> None:
        field_name = CRED_PREFIX + spec.name
        raw = str(cleaned.get(field_name) or "").strip()
        if not raw:
            previous = self.existing.get(spec.name, "")
            clear = bool(cleaned.get(CLEAR_PREFIX + spec.name)) and not spec.required
            if spec.secret and previous and not clear:
                credentials[spec.name] = previous  # em branco = manter o segredo salvo
            elif spec.required:
                self.add_error(field_name, "Informe este segredo." if spec.secret else "Campo obrigatório.")
            return
        try:
            credentials[spec.name] = validate_credential(self.definition.key, spec, raw)
        except CredentialError as exc:
            self.add_error(field_name, str(exc))


class TestMessageForm(StyledFormMixin, forms.Form):
    """Mensagem avulsa de teste para um número digitado (fora de disparos)."""

    __test__ = False  # não é um teste

    to = PhoneField(label="Número de destino")
    text = forms.CharField(
        label="Mensagem",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 1000, "placeholder": "Olá! Esta é uma mensagem de teste do E-Find."}),
    )
    use_template = forms.BooleanField(label="Usar o template hello_world (en_US)", required=False)

    def __init__(self, *args, allow_template: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_template = allow_template
        if not allow_template:
            del self.fields["use_template"]

    def clean(self):
        cleaned = super().clean()
        use_template = bool(cleaned.get("use_template")) and self.allow_template
        cleaned["use_template"] = use_template
        if not use_template and not (cleaned.get("text") or "").strip() and "text" not in self.errors:
            self.add_error("text", "Escreva a mensagem de teste.")
        return cleaned
