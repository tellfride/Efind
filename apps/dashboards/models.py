from django.db import models

from apps.core.models import TimestampedModel


class Dashboard(TimestampedModel):
    """Dashboard personalizável (vários modelos por campanha). widgets = lista de widgets em JSON."""

    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="dashboards")
    owner = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="dashboards"
    )
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    # Visível para toda a equipe com permissão de dashboard (senão, só para o dono)
    shared = models.BooleanField(default=False)
    # Padrão da campanha (shared + sem dono) ou "meu padrão" (dono)
    is_default = models.BooleanField(default=False)
    widgets = models.JSONField(default=list)

    class Meta:
        ordering = ["-is_default", "name"]
        indexes = [models.Index(fields=["campaign"])]

    def __str__(self) -> str:
        return self.name
