from django.db import models

from apps.core.constants import UF_CHOICES, CampaignStatus, Office
from apps.core.models import TimestampedModel


class Campaign(TimestampedModel):
    """Uma campanha = um candidato (tenant). Criada pelo SUPER_ADMIN. É a fronteira de isolamento de dados."""

    slug = models.SlugField(max_length=80, unique=True)
    candidate_name = models.CharField("nome do candidato", max_length=160)
    ballot_name = models.CharField("nome de urna", max_length=120)
    ballot_number = models.CharField("número", max_length=10, blank=True)
    party = models.CharField("partido", max_length=40, blank=True)
    office = models.CharField("cargo", max_length=30, choices=Office.choices)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True, choices=UF_CHOICES)
    election_year = models.PositiveSmallIntegerField("ano da eleição")
    # Logo como data URL (png/jpeg/webp, até ~300 KB) para não depender de armazenamento de arquivos
    logo_url = models.TextField("logo", blank=True)
    # Banner do topo do formulário público: data URL (png/jpeg/webp, proporção 4:1, até ~400 KB)
    banner_url = models.TextField("banner do formulário", blank=True)
    primary_color = models.CharField("cor principal", max_length=7, default="#4f46e5")
    status = models.CharField(max_length=12, choices=CampaignStatus.choices, default=CampaignStatus.ACTIVE)
    voter_goal = models.PositiveIntegerField("meta de cadastros", null=True, blank=True)
    # Texto de consentimento LGPD do formulário público (vazio = texto padrão; aceita {{candidato}})
    consent_text = models.TextField(blank=True)
    form_title = models.CharField(max_length=160, blank=True)
    form_message = models.TextField(blank=True)
    # {"email": "optional", "birth_date": ..., "gender": ..., "address": ..., "electoral": ...} (veja core.constants)
    form_config = models.JSONField(default=dict, blank=True)
    privacy_contact = models.CharField("contato de privacidade", max_length=160, blank=True)

    class Meta:
        ordering = ["ballot_name"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        return self.ballot_name

    @property
    def is_active(self) -> bool:
        return self.status == CampaignStatus.ACTIVE
