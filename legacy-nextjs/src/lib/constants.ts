// Valores "enum" do sistema (SQLite não tem enum nativo: o banco guarda String e validamos aqui).

export const ROLES = ["SUPER_ADMIN", "ADMIN", "COORDENADOR", "CABO"] as const;
export type Role = (typeof ROLES)[number];
/** Papéis que pertencem a uma campanha */
export const CAMPAIGN_ROLES = ["ADMIN", "COORDENADOR", "CABO"] as const;
export type CampaignRole = (typeof CAMPAIGN_ROLES)[number];
/** Papéis cujas permissões o ADMIN configura */
export const CONFIGURABLE_ROLES = ["COORDENADOR", "CABO"] as const;
export type ConfigurableRole = (typeof CONFIGURABLE_ROLES)[number];

export const ROLE_LABELS: Record<Role, string> = {
  SUPER_ADMIN: "Super admin",
  ADMIN: "Administrador",
  COORDENADOR: "Coordenador",
  CABO: "Cabo eleitoral",
};

export const OFFICES = [
  "VEREADOR",
  "PREFEITO",
  "VICE_PREFEITO",
  "DEPUTADO_ESTADUAL",
  "DEPUTADO_DISTRITAL",
  "DEPUTADO_FEDERAL",
  "SENADOR",
  "GOVERNADOR",
  "PRESIDENTE",
  "OUTRO",
] as const;
export type Office = (typeof OFFICES)[number];
export const OFFICE_LABELS: Record<Office, string> = {
  VEREADOR: "Vereador(a)",
  PREFEITO: "Prefeito(a)",
  VICE_PREFEITO: "Vice-prefeito(a)",
  DEPUTADO_ESTADUAL: "Deputado(a) estadual",
  DEPUTADO_DISTRITAL: "Deputado(a) distrital",
  DEPUTADO_FEDERAL: "Deputado(a) federal",
  SENADOR: "Senador(a)",
  GOVERNADOR: "Governador(a)",
  PRESIDENTE: "Presidente",
  OUTRO: "Outro",
};

export const CAMPAIGN_STATUSES = ["ACTIVE", "SUSPENDED"] as const;
export type CampaignStatus = (typeof CAMPAIGN_STATUSES)[number];
export const CAMPAIGN_STATUS_LABELS: Record<CampaignStatus, string> = {
  ACTIVE: "Ativa",
  SUSPENDED: "Suspensa",
};

export const UFS = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
  "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
] as const;
export type UF = (typeof UFS)[number];

export const GENDERS = ["M", "F", "O", "N"] as const;
export type Gender = (typeof GENDERS)[number];
export const GENDER_LABELS: Record<Gender, string> = {
  M: "Masculino",
  F: "Feminino",
  O: "Outro",
  N: "Prefere não informar",
};

export const SUPPORT_LEVELS = ["APOIADOR", "SIMPATIZANTE", "INDECISO", "OPOSITOR"] as const;
export type SupportLevel = (typeof SUPPORT_LEVELS)[number];
export const SUPPORT_LEVEL_LABELS: Record<SupportLevel, string> = {
  APOIADOR: "Apoiador",
  SIMPATIZANTE: "Simpatizante",
  INDECISO: "Indeciso",
  OPOSITOR: "Opositor",
};

export const VOTER_SOURCES = ["LINK", "QRCODE", "MANUAL", "IMPORT"] as const;
export type VoterSource = (typeof VOTER_SOURCES)[number];
export const VOTER_SOURCE_LABELS: Record<VoterSource, string> = {
  LINK: "Link",
  QRCODE: "QR Code",
  MANUAL: "Cadastro manual",
  IMPORT: "Importação",
};

export const GEO_STATUSES = ["PENDING", "OK", "APPROXIMATE", "FAILED"] as const;
export type GeoStatus = (typeof GEO_STATUSES)[number];

export const WHATSAPP_PROVIDERS = ["META_CLOUD", "TWILIO", "DIALOG360", "SANDBOX"] as const;
export type WhatsAppProviderKey = (typeof WHATSAPP_PROVIDERS)[number];

export const CONNECTION_STATUSES = ["DRAFT", "CONNECTED", "ERROR", "DISABLED"] as const;
export type ConnectionStatus = (typeof CONNECTION_STATUSES)[number];
export const CONNECTION_STATUS_LABELS: Record<ConnectionStatus, string> = {
  DRAFT: "Rascunho",
  CONNECTED: "Conectado",
  ERROR: "Erro",
  DISABLED: "Desativado",
};

export const TEMPLATE_CATEGORIES = [
  "BOAS_VINDAS",
  "CONVITE",
  "AGRADECIMENTO",
  "LEMBRETE",
  "INFORMATIVO",
  "PESQUISA",
] as const;
export type TemplateCategory = (typeof TEMPLATE_CATEGORIES)[number];
export const TEMPLATE_CATEGORY_LABELS: Record<TemplateCategory, string> = {
  BOAS_VINDAS: "Boas-vindas",
  CONVITE: "Convite / evento",
  AGRADECIMENTO: "Agradecimento",
  LEMBRETE: "Lembrete",
  INFORMATIVO: "Informativo",
  PESQUISA: "Pesquisa",
};

export const TEMPLATE_TYPES = ["TEXT", "IMAGE", "DOCUMENT", "VIDEO"] as const;
export type TemplateType = (typeof TEMPLATE_TYPES)[number];
export const TEMPLATE_TYPE_LABELS: Record<TemplateType, string> = {
  TEXT: "Texto",
  IMAGE: "Imagem + legenda",
  DOCUMENT: "Documento (PDF)",
  VIDEO: "Vídeo + legenda",
};

export const BROADCAST_STATUSES = [
  "DRAFT",
  "SCHEDULED",
  "RUNNING",
  "PAUSED",
  "COMPLETED",
  "CANCELLED",
  "FAILED",
] as const;
export type BroadcastStatus = (typeof BROADCAST_STATUSES)[number];
export const BROADCAST_STATUS_LABELS: Record<BroadcastStatus, string> = {
  DRAFT: "Rascunho",
  SCHEDULED: "Agendado",
  RUNNING: "Enviando",
  PAUSED: "Pausado",
  COMPLETED: "Concluído",
  CANCELLED: "Cancelado",
  FAILED: "Falhou",
};

export const MESSAGE_STATUSES = [
  "PENDING",
  "SENDING",
  "SENT",
  "DELIVERED",
  "READ",
  "FAILED",
  "SKIPPED",
] as const;
export type MessageStatus = (typeof MESSAGE_STATUSES)[number];
export const MESSAGE_STATUS_LABELS: Record<MessageStatus, string> = {
  PENDING: "Na fila",
  SENDING: "Enviando",
  SENT: "Enviada",
  DELIVERED: "Entregue",
  READ: "Lida",
  FAILED: "Falhou",
  SKIPPED: "Ignorada",
};

/** Palavras que, recebidas pelo WhatsApp, descadastram o eleitor dos disparos */
export const OPT_OUT_KEYWORDS = ["SAIR", "PARAR", "STOP", "CANCELAR", "DESCADASTRAR", "REMOVER"] as const;

/** Campos opcionais do formulário público de cadastro e se são exibidos/obrigatórios */
export type FormFieldMode = "hidden" | "optional" | "required";
export interface FormConfig {
  email: FormFieldMode;
  birthDate: FormFieldMode;
  gender: FormFieldMode;
  address: FormFieldMode; // CEP + logradouro + número + bairro + cidade
  electoral: FormFieldMode; // zona e seção eleitoral
}
export const DEFAULT_FORM_CONFIG: FormConfig = {
  email: "optional",
  birthDate: "optional",
  gender: "optional",
  address: "required",
  electoral: "hidden",
};

export function parseFormConfig(value: unknown): FormConfig {
  const cfg = { ...DEFAULT_FORM_CONFIG };
  if (value && typeof value === "object") {
    for (const key of Object.keys(DEFAULT_FORM_CONFIG) as (keyof FormConfig)[]) {
      const v = (value as Record<string, unknown>)[key];
      if (v === "hidden" || v === "optional" || v === "required") cfg[key] = v;
    }
  }
  return cfg;
}

export const DEFAULT_CONSENT_TEXT =
  "Autorizo a campanha de {{candidato}} a tratar meus dados pessoais informados neste formulário " +
  "(nome, telefone, endereço e demais dados) para fins de comunicação política e organização da campanha, " +
  "nos termos da Lei Geral de Proteção de Dados (Lei nº 13.709/2018). Sei que posso solicitar a correção " +
  "ou exclusão dos meus dados a qualquer momento.";

export const DEFAULT_WHATSAPP_OPTIN_TEXT =
  "Aceito receber mensagens da campanha pelo WhatsApp. Posso cancelar a qualquer momento respondendo SAIR.";
