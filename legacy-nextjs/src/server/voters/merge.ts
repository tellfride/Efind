// Regras puras de atualização de eleitor: recadastro com telefone já existente e mudança de endereço.

/** Campos que um recadastro pode completar (somente se estiverem vazios no cadastro existente) */
export const FILLABLE_FIELDS = [
  "email",
  "birthDate",
  "gender",
  "cep",
  "street",
  "number",
  "complement",
  "neighborhood",
  "city",
  "state",
  "electoralZone",
  "electoralSection",
] as const;
export type FillableField = (typeof FILLABLE_FIELDS)[number];

/** Campos que alteram a geocodificação (o número não entra: coordenadas são do CEP/logradouro) */
export const GEO_ADDRESS_FIELDS = ["cep", "street", "neighborhood", "city", "state"] as const;
export type GeoAddressField = (typeof GEO_ADDRESS_FIELDS)[number];

type FillableValue = string | Date | null | undefined;

export type ExistingVoterForMerge = Record<FillableField, FillableValue> & {
  whatsappOptIn: boolean;
  optOutAt: Date | null;
};

export interface DuplicateMergeInput {
  existing: ExistingVoterForMerge;
  incoming: Partial<Record<FillableField, FillableValue>>;
  /** O eleitor marcou agora a autorização de WhatsApp? */
  whatsappOptIn: boolean;
  consentText: string;
  consentIp: string;
  now: Date;
}

export interface DuplicateMergePlan {
  /** Dados para prisma.voter.update */
  data: Partial<Record<FillableField, string | Date>> & {
    consentAt: Date;
    consentIp: string;
    consentText: string;
    whatsappOptIn?: true;
    optOutAt?: null;
    geoStatus?: "PENDING";
    latitude?: null;
    longitude?: null;
  };
  /** Campos completados com dados novos */
  filled: FillableField[];
  /** Endereço mudou → precisa geocodificar de novo */
  needsGeocode: boolean;
}

const isEmpty = (v: FillableValue) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");

/**
 * Recadastro pelo link com telefone já cadastrado na campanha:
 *  - nunca sobrescreve dados existentes (só completa campos vazios) e mantém quem cadastrou;
 *  - renova o consentimento LGPD (data, IP e texto);
 *  - reativa o WhatsApp (opt-in e remove descadastro) SOMENTE se a caixa foi marcada agora.
 */
export function planDuplicateMerge(input: DuplicateMergeInput): DuplicateMergePlan {
  const data: DuplicateMergePlan["data"] = {
    consentAt: input.now,
    consentIp: input.consentIp,
    consentText: input.consentText,
  };
  const filled: FillableField[] = [];
  for (const key of FILLABLE_FIELDS) {
    const incoming = input.incoming[key];
    if (isEmpty(input.existing[key]) && !isEmpty(incoming)) {
      data[key] = incoming as string | Date;
      filled.push(key);
    }
  }
  if (input.whatsappOptIn) {
    data.whatsappOptIn = true;
    data.optOutAt = null;
  }
  const needsGeocode = filled.some((k) => (GEO_ADDRESS_FIELDS as readonly string[]).includes(k));
  if (needsGeocode) {
    data.geoStatus = "PENDING";
    data.latitude = null;
    data.longitude = null;
  }
  return { data, filled, needsGeocode };
}

function normalizeForCompare(v: string | null | undefined): string {
  return (v ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
}

/** O endereço relevante para o mapa mudou? (ignora diferenças de caixa, acentos e espaços) */
export function geoAddressChanged(
  before: Partial<Record<GeoAddressField, string | null>>,
  after: Partial<Record<GeoAddressField, string | null>>,
): boolean {
  return GEO_ADDRESS_FIELDS.some((k) => normalizeForCompare(before[k]) !== normalizeForCompare(after[k]));
}
