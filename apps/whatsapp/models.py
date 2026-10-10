from django.db import models

from apps.core.constants import ConnectionStatus, WhatsAppProvider
from apps.core.models import TimestampedModel, UUIDModel


class WhatsAppConnection(TimestampedModel):
    """Conexão com um provedor oficial de WhatsApp (credenciais criptografadas com AES-256-GCM)."""

    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="whatsapp_connections")
    name = models.CharField(max_length=100)
    provider = models.CharField(max_length=12, choices=WhatsAppProvider.choices)
    status = models.CharField(max_length=10, choices=ConnectionStatus.choices, default=ConnectionStatus.DRAFT)
    phone_number = models.CharField("número exibido", max_length=30, blank=True)
    # JSON criptografado — veja apps.core.crypto.encrypt_json
    credentials = models.TextField()
    # Token aleatório usado na URL do webhook e como verify token da Meta
    webhook_token = models.CharField(max_length=64, unique=True)
    is_default = models.BooleanField(default=False)
    rate_per_minute = models.PositiveIntegerField(default=20)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-is_default", "name"]
        indexes = [models.Index(fields=["campaign"])]

    def __str__(self) -> str:
        return self.name


class InboundMessage(UUIDModel):
    """Mensagens recebidas via webhook (descadastro "SAIR" e histórico)."""

    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="inbound_messages")
    connection = models.ForeignKey(WhatsAppConnection, null=True, on_delete=models.SET_NULL, related_name="inbound")
    from_phone = models.CharField(max_length=20)
    body = models.TextField(blank=True)
    voter = models.ForeignKey("voters.Voter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # True quando interpretada como pedido de descadastro
    is_opt_out = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["campaign", "received_at"])]
