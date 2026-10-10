// Exportação de eleitores em CSV: colunas e conversão de cada registro (puro).
import {
  GENDER_LABELS,
  SUPPORT_LEVEL_LABELS,
  VOTER_SOURCE_LABELS,
  type Gender,
  type SupportLevel,
  type VoterSource,
} from "@/lib/constants";
import { formatPhone } from "@/lib/phone";
import { formatDateTime, parseTags } from "@/lib/utils";
import {
  WHATSAPP_STATUS_LABELS,
  ageFromBirthDate,
  formatBirthDate,
  formatCepDisplay,
  saoPauloIsoDate,
  whatsappStatusOf,
} from "@/components/voters/voter-utils";

export const MAX_EXPORT_ROWS = 50_000;

export const VOTER_EXPORT_COLUMNS = [
  { key: "nome", label: "Nome" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "email", label: "E-mail" },
  { key: "nascimento", label: "Nascimento" },
  { key: "idade", label: "Idade" },
  { key: "genero", label: "Gênero" },
  { key: "cep", label: "CEP" },
  { key: "rua", label: "Logradouro" },
  { key: "numero", label: "Número" },
  { key: "complemento", label: "Complemento" },
  { key: "bairro", label: "Bairro" },
  { key: "cidade", label: "Cidade" },
  { key: "uf", label: "UF" },
  { key: "zona", label: "Zona eleitoral" },
  { key: "secao", label: "Seção eleitoral" },
  { key: "apoio", label: "Nível de apoio" },
  { key: "tags", label: "Tags" },
  { key: "origem", label: "Origem" },
  { key: "cadastradoPor", label: "Cadastrado por" },
  { key: "situacaoWhatsapp", label: "Situação WhatsApp" },
  { key: "consentimento", label: "Consentimento LGPD em" },
  { key: "cadastradoEm", label: "Cadastrado em" },
  { key: "observacoes", label: "Observações" },
] as const;

export interface ExportableVoter {
  name: string;
  phone: string;
  email: string | null;
  birthDate: Date | null;
  gender: string | null;
  cep: string | null;
  street: string | null;
  number: string | null;
  complement: string | null;
  neighborhood: string | null;
  city: string | null;
  state: string | null;
  electoralZone: string | null;
  electoralSection: string | null;
  supportLevel: string | null;
  tags: string | null;
  notes: string | null;
  source: string;
  consentAt: Date | null;
  whatsappOptIn: boolean;
  optOutAt: Date | null;
  createdAt: Date;
  registeredBy: { name: string } | null;
}

/** Converte um eleitor numa linha do CSV (rótulos em pt-BR, datas no fuso de São Paulo) */
export function voterToExportRow(v: ExportableVoter, now: Date = new Date()): Record<string, string | number | null> {
  return {
    nome: v.name,
    whatsapp: formatPhone(v.phone),
    email: v.email,
    nascimento: v.birthDate ? formatBirthDate(v.birthDate) : null,
    idade: v.birthDate ? ageFromBirthDate(v.birthDate, now) : null,
    genero: v.gender ? (GENDER_LABELS[v.gender as Gender] ?? v.gender) : null,
    cep: v.cep ? formatCepDisplay(v.cep) : null,
    rua: v.street,
    numero: v.number,
    complemento: v.complement,
    bairro: v.neighborhood,
    cidade: v.city,
    uf: v.state,
    zona: v.electoralZone,
    secao: v.electoralSection,
    apoio: v.supportLevel ? (SUPPORT_LEVEL_LABELS[v.supportLevel as SupportLevel] ?? v.supportLevel) : null,
    tags: parseTags(v.tags).join(", ") || null,
    origem: VOTER_SOURCE_LABELS[v.source as VoterSource] ?? v.source,
    cadastradoPor: v.registeredBy?.name ?? null,
    situacaoWhatsapp: WHATSAPP_STATUS_LABELS[whatsappStatusOf(v)],
    consentimento: v.consentAt ? formatDateTime(v.consentAt) : null,
    cadastradoEm: formatDateTime(v.createdAt),
    observacoes: v.notes,
  };
}

export function exportFileName(now: Date = new Date()): string {
  return `eleitores-${saoPauloIsoDate(now)}.csv`;
}
