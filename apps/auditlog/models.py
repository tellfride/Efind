from django.db import models

from apps.core.models import UUIDModel


class AuditLog(UUIDModel):
    """Trilha de auditoria (LGPD: quem acessou/alterou/exportou dados). Escrita via apps.auditlog.service.audit()."""

    campaign = models.ForeignKey(
        "campaigns.Campaign", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    user = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60)  # ex.: auth.login, voter.create (veja apps.auditlog.actions)
    entity = models.CharField(max_length=40, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["campaign", "created_at"]), models.Index(fields=["user"])]
