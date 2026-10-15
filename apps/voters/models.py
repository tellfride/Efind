from django.db import models

from apps.core.constants import Gender, GeoStatus, SupportLevel, VoterSource
from apps.core.models import TimestampedModel


class Voter(TimestampedModel):
    """Apoiador cadastrado. Sempre vinculado a quem cadastrou (registered_by)."""

    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="voters")
    # RESTRICT: não se exclui um usuário que tenha apoiadores (transfira antes); ao excluir a campanha inteira, passa.
    registered_by = models.ForeignKey("accounts.User", on_delete=models.RESTRICT, related_name="registered_voters")
    name = models.CharField("nome", max_length=160)
    # Somente dígitos com DDI: 55 + DDD + número (ex.: 5511987654321)
    phone = models.CharField("WhatsApp", max_length=20)
    email = models.EmailField("e-mail", max_length=254, blank=True)
    birth_date = models.DateField("nascimento", null=True, blank=True)
    gender = models.CharField("gênero", max_length=1, blank=True, choices=Gender.choices)
    electoral_zone = models.CharField("zona eleitoral", max_length=10, blank=True)
    electoral_section = models.CharField("seção eleitoral", max_length=10, blank=True)
    cep = models.CharField("CEP", max_length=8, blank=True)  # 8 dígitos
    street = models.CharField("logradouro", max_length=160, blank=True)
    number = models.CharField("número", max_length=20, blank=True)
    complement = models.CharField("complemento", max_length=100, blank=True)
    neighborhood = models.CharField("bairro", max_length=100, blank=True)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    # Coordenadas no nível do CEP/logradouro (não do imóvel), para o mapa
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geo_status = models.CharField(max_length=12, choices=GeoStatus.choices, default=GeoStatus.PENDING)
    support_level = models.CharField("nível de apoio", max_length=15, blank=True, choices=SupportLevel.choices)
    # Tags normalizadas com vírgulas nas pontas: ",saude,jovem," (veja core.utils.serialize_tags)
    tags = models.CharField(max_length=500, blank=True)
    notes = models.TextField("observações", blank=True)
    source = models.CharField("origem", max_length=10, choices=VoterSource.choices, default=VoterSource.LINK)
    # Consentimento LGPD para tratamento dos dados
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_ip = models.GenericIPAddressField(null=True, blank=True)
    consent_text = models.TextField(blank=True)
    # Consentimento para receber mensagens de WhatsApp
    whatsapp_opt_in = models.BooleanField(default=False)
    # Descadastro (respondeu SAIR ou pediu remoção)
    opt_out_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["campaign", "phone"], name="uniq_voter_phone_per_campaign")]
        indexes = [
            models.Index(fields=["campaign", "registered_by"]),
            models.Index(fields=["campaign", "neighborhood"]),
            models.Index(fields=["campaign", "city"]),
            models.Index(fields=["campaign", "created_at"]),
            models.Index(fields=["geo_status"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_messageable(self) -> bool:
        """Apto a receber disparos: consentiu e não pediu descadastro."""
        return bool(self.whatsapp_opt_in and self.opt_out_at is None and self.consent_at is not None)
