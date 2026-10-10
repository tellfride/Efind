from django.db import models

from apps.core.constants import BroadcastStatus, MessageStatus, TemplateCategory, TemplateType
from apps.core.models import TimestampedModel, UUIDModel


class MessageTemplate(TimestampedModel):
    """Modelo de mensagem com variáveis {{nome}}, {{bairro}}... (veja apps.core.template_vars)."""

    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="message_templates")
    created_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=15, choices=TemplateCategory.choices, default=TemplateCategory.INFORMATIVO)
    type = models.CharField(max_length=10, choices=TemplateType.choices, default=TemplateType.TEXT)
    body = models.TextField()
    media_url = models.URLField(max_length=500, blank=True)
    # API oficial (Meta/360dialog/Twilio): nome do template aprovado (ou ContentSid HX... da Twilio),
    # idioma e ordem das variáveis ({{1}}, {{2}}...) como lista de chaves de TEMPLATE_VARIABLES
    provider_template_name = models.CharField(max_length=120, blank=True)
    provider_template_language = models.CharField(max_length=10, blank=True, default="pt_BR")
    provider_variables = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["campaign"])]

    def __str__(self) -> str:
        return self.name


class Broadcast(TimestampedModel):
    """Disparo: envio em massa para um público segmentado de eleitores que consentiram."""

    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="broadcasts")
    name = models.CharField(max_length=160)
    template = models.ForeignKey(MessageTemplate, null=True, on_delete=models.SET_NULL, related_name="broadcasts")
    connection = models.ForeignKey(
        "whatsapp.WhatsAppConnection", null=True, on_delete=models.SET_NULL, related_name="broadcasts"
    )
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="broadcasts")
    status = models.CharField(max_length=10, choices=BroadcastStatus.choices, default=BroadcastStatus.DRAFT)
    # Filtros de eleitores (apps.core.voter_filters) que definem o público
    filters = models.JSONField(default=dict)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    rate_per_minute = models.PositiveIntegerField(default=20)
    total_recipients = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    delivered_count = models.PositiveIntegerField(default=0)
    read_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self) -> str:
        return self.name


class BroadcastMessage(UUIDModel):
    """Uma mensagem individual de um disparo."""

    broadcast = models.ForeignKey(Broadcast, on_delete=models.CASCADE, related_name="messages")
    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="+")
    voter = models.ForeignKey("voters.Voter", null=True, on_delete=models.SET_NULL, related_name="broadcast_messages")
    phone = models.CharField(max_length=20)
    rendered_body = models.TextField()
    status = models.CharField(max_length=10, choices=MessageStatus.choices, default=MessageStatus.PENDING)
    provider_message_id = models.CharField(max_length=200, blank=True)
    error = models.CharField(max_length=300, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["broadcast", "status"]),
            models.Index(fields=["provider_message_id"]),
            models.Index(fields=["campaign"]),
        ]
