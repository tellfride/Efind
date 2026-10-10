"""Formulários do módulo: modelo de mensagem e assistente de disparo."""

from __future__ import annotations

import json
import uuid
from urllib.parse import urlparse

from django import forms
from django.utils import timezone

from apps.core.access import voters_queryset
from apps.core.constants import TemplateCategory, TemplateType
from apps.core.forms import StyledFormMixin
from apps.core.template_vars import TEMPLATE_VARIABLES
from apps.core.voter_filters import sanitize_voter_filters
from apps.whatsapp import registry

from .logic import (
    DEFAULT_RATE_PER_MINUTE,
    MAX_RATE_PER_MINUTE,
    PROVIDER_LANGUAGE_RE,
    PROVIDER_TEMPLATE_NAME_RE,
    TEMPLATE_BODY_MAX,
    send_blocker,
    validate_schedule,
)
from .models import MessageTemplate
from .queries import connected_connections, team_ids_in_scope, template_scope

MAX_PROVIDER_VARIABLES = 20
VARIABLE_CHOICES = [(v["key"], v["label"]) for v in TEMPLATE_VARIABLES]


def is_https_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


# --------------------------------------------------------------------------------------------- modelo de mensagem


class TemplateForm(StyledFormMixin, forms.Form):
    name = forms.CharField(
        label="Nome do modelo",
        min_length=3,
        max_length=120,
        help_text="Só para você identificar o modelo; o eleitor não vê este nome.",
        error_messages={"min_length": "Use pelo menos 3 caracteres."},
    )
    category = forms.ChoiceField(label="Categoria", choices=TemplateCategory.choices)
    type = forms.ChoiceField(label="Tipo da mensagem", choices=TemplateType.choices)
    media_url = forms.URLField(
        label="Link da mídia",
        required=False,
        max_length=500,
        assume_scheme="https",
        help_text="Endereço https:// público da imagem, do PDF ou do vídeo (o provedor baixa o arquivo).",
    )
    body = forms.CharField(
        label="Texto da mensagem",
        max_length=TEMPLATE_BODY_MAX,
        widget=forms.Textarea(
            attrs={
                "rows": 10,
                "x-ref": "body",
                "x-model": "body",
                "placeholder": "Olá, {{primeiro_nome}}! Aqui é a equipe de {{candidato}}...",
            }
        ),
        error_messages={
            "required": "Escreva o texto da mensagem.",
            "max_length": f"O texto pode ter no máximo {TEMPLATE_BODY_MAX} caracteres.",
        },
    )
    provider_template_name = forms.CharField(
        label="Nome do template aprovado",
        required=False,
        max_length=120,
        help_text="Nome exato do template aprovado (minúsculas, números e _) ou o ContentSid da Twilio (HX…).",
    )
    provider_template_language = forms.CharField(
        label="Idioma do template", required=False, max_length=10, help_text="Ex.: pt_BR, en_US, es."
    )
    provider_variables = forms.MultipleChoiceField(required=False, choices=VARIABLE_CHOICES)

    def __init__(self, *args, read_only: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type"].widget.attrs["x-model"] = "kind"
        self.fields["media_url"].widget.attrs["x-model"] = "mediaUrl"
        if read_only:
            for field in self.fields.values():
                field.disabled = True

    def clean_body(self):
        body = self.cleaned_data["body"].replace("\r\n", "\n").replace("\r", "\n")
        if not body.strip():
            raise forms.ValidationError("Escreva o texto da mensagem.")
        return body

    def clean_provider_template_name(self):
        value = (self.cleaned_data.get("provider_template_name") or "").strip()
        if value and not PROVIDER_TEMPLATE_NAME_RE.match(value):
            raise forms.ValidationError(
                "Use o nome exato do template aprovado (letras minúsculas, números e _) "
                "ou o ContentSid da Twilio (HX…)."
            )
        return value

    def clean_provider_template_language(self):
        value = (self.cleaned_data.get("provider_template_language") or "").strip() or "pt_BR"
        if not PROVIDER_LANGUAGE_RE.match(value):
            raise forms.ValidationError("Idioma inválido (ex.: pt_BR).")
        return value

    def clean_provider_variables(self):
        values = self.cleaned_data.get("provider_variables") or []
        if len(values) > MAX_PROVIDER_VARIABLES:
            raise forms.ValidationError(f"Use no máximo {MAX_PROVIDER_VARIABLES} parâmetros.")
        return list(values)

    def clean(self):
        data = super().clean()
        kind = data.get("type")
        if kind and kind != TemplateType.TEXT:
            url = data.get("media_url")
            if "media_url" not in self.errors:
                if not url:
                    self.add_error("media_url", "Informe o link (https) da mídia.")
                elif not is_https_url(url):
                    self.add_error("media_url", "O link da mídia precisa ser um endereço https:// válido.")
        elif kind:
            data["media_url"] = ""
        return data

    @property
    def selected_variables(self) -> list[str]:
        """Parâmetros do template oficial na ordem enviada (para reexibir o formulário)."""
        if self.is_bound:
            raw = self.data.getlist("provider_variables") if hasattr(self.data, "getlist") else []
            valid = {k for k, _ in VARIABLE_CHOICES}
            return [v for v in raw if v in valid][:MAX_PROVIDER_VARIABLES]
        return list(self.initial.get("provider_variables") or [])


def template_initial(template: MessageTemplate) -> dict:
    return {
        "name": template.name,
        "category": template.category,
        "type": template.type,
        "media_url": template.media_url,
        "body": template.body,
        "provider_template_name": template.provider_template_name,
        "provider_template_language": template.provider_template_language or "pt_BR",
        "provider_variables": [v for v in (template.provider_variables or []) if isinstance(v, str)],
    }


# --------------------------------------------------------------------------------------------- disparo


class BroadcastForm(StyledFormMixin, forms.Form):
    """Assistente de disparo. Modelo e conexão são validados contra a campanha do usuário; o público contra o
    escopo dele. `messageable` nunca é salvo nos filtros (é forçado na materialização)."""

    INVALID_FILTERS = "Os filtros do público são inválidos. Revise o público e tente de novo."

    name = forms.CharField(
        label="Nome do disparo",
        min_length=3,
        max_length=120,
        error_messages={"min_length": "Dê um nome com pelo menos 3 caracteres."},
    )
    template = forms.CharField(label="Modelo de mensagem", error_messages={"required": "Escolha o modelo de mensagem."})
    connection = forms.CharField(label="Conexão de WhatsApp", error_messages={"required": "Escolha a conexão de WhatsApp."})
    rate_per_minute = forms.IntegerField(
        label="Velocidade (mensagens por minuto)",
        min_value=1,
        max_value=MAX_RATE_PER_MINUTE,
        initial=DEFAULT_RATE_PER_MINUTE,
        error_messages={
            "required": "Informe a velocidade de envio.",
            "invalid": "Use um número inteiro.",
            "min_value": "Mínimo de 1 mensagem por minuto.",
            "max_value": "Velocidade muito alta.",
        },
    )
    mode = forms.ChoiceField(
        choices=[("now", "Enviar agora"), ("schedule", "Agendar")],
        error_messages={"required": "Escolha quando enviar.", "invalid_choice": "Escolha quando enviar."},
    )
    scheduled_at = forms.CharField(label="Data e hora", required=False, max_length=32)
    filters = forms.CharField(required=False, widget=forms.HiddenInput)
    consent = forms.BooleanField(
        required=True,
        label="Confirmo que todos os destinatários consentiram em receber mensagens desta campanha",
        error_messages={"required": "Confirme o consentimento dos destinatários."},
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.eligible = 0
        self.parsed_filters: dict = {}
        self.template_obj: MessageTemplate | None = None
        self.connection_obj = None
        self.scheduled_for = None

    # --- campos individuais ---

    @staticmethod
    def _uuid(value: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(value).strip())
        except (ValueError, TypeError, AttributeError):
            return None

    def clean_template(self):
        pk = self._uuid(self.cleaned_data["template"])
        template = template_scope(self.user).filter(pk=pk).first() if pk else None
        if template is None:
            raise forms.ValidationError("Modelo de mensagem não encontrado.")
        self.template_obj = template
        return template

    def clean_connection(self):
        pk = self._uuid(self.cleaned_data["connection"])
        connection = connected_connections(self.user).filter(pk=pk).first() if pk else None
        if connection is None:
            raise forms.ValidationError("Conexão de WhatsApp não encontrada ou não conectada.")
        self.connection_obj = connection
        return connection

    def clean_filters(self):
        raw = (self.cleaned_data.get("filters") or "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise forms.ValidationError(self.INVALID_FILTERS) from None
        if not isinstance(value, dict):
            raise forms.ValidationError(self.INVALID_FILTERS)
        if isinstance(value.get("q"), str):
            value["q"] = value["q"].strip()
        sent = {k: v for k, v in value.items() if k != "messageable" and v not in (None, "", [])}
        clean = sanitize_voter_filters(sent)
        # Filtro descartado = público maior do que o usuário imagina: recusa em vez de ampliar em silêncio
        if clean != sent:
            raise forms.ValidationError(self.INVALID_FILTERS)
        if not team_ids_in_scope(self.user, clean):
            raise forms.ValidationError("Os filtros de equipe selecionados não pertencem à sua rede.")
        self.parsed_filters = clean
        return clean

    # --- regras entre campos ---

    def clean(self):
        data = super().clean()
        now = timezone.now()

        connection = data.get("connection")
        template = data.get("template")
        if connection is not None:
            rate = data.get("rate_per_minute")
            if rate and rate > connection.rate_per_minute:
                self.add_error(
                    "rate_per_minute", f"O limite desta conexão é de {connection.rate_per_minute} mensagens por minuto."
                )
            definition = registry.get_provider_definition(connection.provider)
            blocker = send_blocker(
                connection=connection,
                campaign_id=self.user.campaign_id,
                provider_known=definition is not None,
                requires_approved_template=bool(definition and definition.requires_approved_template),
                template=template,
            )
            if blocker is not None and template is not None:
                if blocker.code == "template_required":
                    self.add_error(
                        "template",
                        "A conexão escolhida usa a API oficial, que exige template aprovado. Informe o nome do "
                        "template aprovado no modelo ou escolha outra conexão.",
                    )
                else:
                    self.add_error("connection", blocker.message)

        if data.get("mode") == "schedule":
            check = validate_schedule(data.get("scheduled_at"), now)
            if check.ok:
                self.scheduled_for = check.date
            else:
                self.add_error("scheduled_at", check.error)
        elif data.get("mode") == "now":
            self.scheduled_for = now

        if "filters" not in self.errors and not self.errors.get("name") and "filters" in data:
            self.eligible = voters_queryset(self.user, {**data["filters"], "messageable": True}).count()
            if self.eligible == 0 and not self.errors:
                raise forms.ValidationError(
                    "Nenhum eleitor deste público autorizou receber mensagens pelo WhatsApp. Ajuste os filtros."
                )
        return data
