"""Valores "enum" do sistema e rótulos em pt-BR. Usados como `choices` nos models e nos templates."""

from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super admin"
    ADMIN = "ADMIN", "Administrador"
    COORDENADOR = "COORDENADOR", "Coordenador"
    CABO = "CABO", "Cabo eleitoral"


# Papéis que pertencem a uma campanha
CAMPAIGN_ROLES = (Role.ADMIN, Role.COORDENADOR, Role.CABO)
# Papéis cujas permissões o ADMIN configura
CONFIGURABLE_ROLES = (Role.COORDENADOR, Role.CABO)


class Office(models.TextChoices):
    VEREADOR = "VEREADOR", "Vereador(a)"
    PREFEITO = "PREFEITO", "Prefeito(a)"
    VICE_PREFEITO = "VICE_PREFEITO", "Vice-prefeito(a)"
    DEPUTADO_ESTADUAL = "DEPUTADO_ESTADUAL", "Deputado(a) estadual"
    DEPUTADO_DISTRITAL = "DEPUTADO_DISTRITAL", "Deputado(a) distrital"
    DEPUTADO_FEDERAL = "DEPUTADO_FEDERAL", "Deputado(a) federal"
    SENADOR = "SENADOR", "Senador(a)"
    GOVERNADOR = "GOVERNADOR", "Governador(a)"
    PRESIDENTE = "PRESIDENTE", "Presidente"
    OUTRO = "OUTRO", "Outro"


class CampaignStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Ativa"
    SUSPENDED = "SUSPENDED", "Suspensa"


UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]  # fmt: skip
UF_CHOICES = [(uf, uf) for uf in UFS]


class Gender(models.TextChoices):
    M = "M", "Masculino"
    F = "F", "Feminino"
    O = "O", "Outro"  # noqa: E741
    N = "N", "Prefere não informar"


class SupportLevel(models.TextChoices):
    APOIADOR = "APOIADOR", "Apoiador"
    SIMPATIZANTE = "SIMPATIZANTE", "Simpatizante"
    INDECISO = "INDECISO", "Indeciso"
    OPOSITOR = "OPOSITOR", "Opositor"


class VoterSource(models.TextChoices):
    LINK = "LINK", "Link"
    QRCODE = "QRCODE", "QR Code"
    MANUAL = "MANUAL", "Cadastro manual"
    IMPORT = "IMPORT", "Importação"


class GeoStatus(models.TextChoices):
    PENDING = "PENDING", "Pendente"
    OK = "OK", "Localizado"
    APPROXIMATE = "APPROXIMATE", "Aproximado"
    FAILED = "FAILED", "Não localizado"


class WhatsAppProvider(models.TextChoices):
    META_CLOUD = "META_CLOUD", "WhatsApp Business Platform (Meta Cloud API)"
    TWILIO = "TWILIO", "Twilio"
    DIALOG360 = "DIALOG360", "360dialog"
    SANDBOX = "SANDBOX", "Simulador (testes)"


class ConnectionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Rascunho"
    CONNECTED = "CONNECTED", "Conectado"
    ERROR = "ERROR", "Erro"
    DISABLED = "DISABLED", "Desativado"


class TemplateCategory(models.TextChoices):
    BOAS_VINDAS = "BOAS_VINDAS", "Boas-vindas"
    CONVITE = "CONVITE", "Convite / evento"
    AGRADECIMENTO = "AGRADECIMENTO", "Agradecimento"
    LEMBRETE = "LEMBRETE", "Lembrete"
    INFORMATIVO = "INFORMATIVO", "Informativo"
    PESQUISA = "PESQUISA", "Pesquisa"


class TemplateType(models.TextChoices):
    TEXT = "TEXT", "Texto"
    IMAGE = "IMAGE", "Imagem + legenda"
    DOCUMENT = "DOCUMENT", "Documento (PDF)"
    VIDEO = "VIDEO", "Vídeo + legenda"


class BroadcastStatus(models.TextChoices):
    DRAFT = "DRAFT", "Rascunho"
    SCHEDULED = "SCHEDULED", "Agendado"
    RUNNING = "RUNNING", "Enviando"
    PAUSED = "PAUSED", "Pausado"
    COMPLETED = "COMPLETED", "Concluído"
    CANCELLED = "CANCELLED", "Cancelado"
    FAILED = "FAILED", "Falhou"


class MessageStatus(models.TextChoices):
    PENDING = "PENDING", "Na fila"
    SENDING = "SENDING", "Enviando"
    SENT = "SENT", "Enviada"
    DELIVERED = "DELIVERED", "Entregue"
    READ = "READ", "Lida"
    FAILED = "FAILED", "Falhou"
    SKIPPED = "SKIPPED", "Ignorada"


# Palavras que, recebidas pelo WhatsApp, descadastram o apoiador dos disparos
OPT_OUT_KEYWORDS = ("SAIR", "PARAR", "STOP", "CANCELAR", "DESCADASTRAR", "REMOVER")

# --- Configuração dos campos opcionais do formulário público de cadastro -------------------------
FORM_FIELD_MODES = ("hidden", "optional", "required")
DEFAULT_FORM_CONFIG = {
    "email": "optional",
    "birth_date": "optional",
    "gender": "optional",
    "address": "required",  # CEP + logradouro + número + bairro + cidade
    "electoral": "hidden",  # zona e seção eleitoral
}


def parse_form_config(value) -> dict:
    """Mescla a configuração salva (JSON) com o padrão, ignorando valores inválidos."""
    cfg = dict(DEFAULT_FORM_CONFIG)
    if isinstance(value, dict):
        for key in DEFAULT_FORM_CONFIG:
            v = value.get(key)
            if v in FORM_FIELD_MODES:
                cfg[key] = v
    return cfg


DEFAULT_CONSENT_TEXT = (
    "Autorizo a campanha de {{candidato}} a tratar meus dados pessoais informados neste formulário "
    "(nome, telefone, endereço e demais dados) para fins de comunicação política e organização da campanha, "
    "nos termos da Lei Geral de Proteção de Dados (Lei nº 13.709/2018). Sei que posso solicitar a correção "
    "ou exclusão dos meus dados a qualquer momento."
)

DEFAULT_WHATSAPP_OPTIN_TEXT = (
    "Aceito receber mensagens da campanha pelo WhatsApp. Posso cancelar a qualquer momento respondendo SAIR."
)


def label_of(choices_cls, value, default: str = "") -> str:
    """Rótulo de um valor de TextChoices ("ADMIN" → "Administrador")."""
    try:
        return choices_cls(value).label
    except ValueError:
        return default or str(value or "")
