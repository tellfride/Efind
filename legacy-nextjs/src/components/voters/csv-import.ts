// Importação de eleitores por CSV — funções puras usadas na pré-visualização (navegador)
// e revalidadas na Server Action (servidor). Nenhum dado sai daqui sem passar por validateImportRecord.
import { GENDERS, SUPPORT_LEVELS, UFS, type Gender, type SupportLevel } from "@/lib/constants";
import { normalizeBrPhone } from "@/lib/phone";
import { normalizeText, serializeTags, titleCase } from "@/lib/utils";
import {
  MAX_VOTER_AGE,
  MIN_VOTER_AGE,
  ageFromBirthDate,
  hasLetter,
  normalizeCepInput,
  parseBirthDateInput,
  smartCase,
} from "./voter-utils";

export const MAX_IMPORT_ROWS = 5000;

export const IMPORT_FIELDS = [
  { key: "nome", label: "Nome", required: true, aliases: ["nome", "nomecompleto", "name", "eleitor", "nomedoeleitor", "nomeeleitor"] },
  {
    key: "telefone",
    label: "Telefone / WhatsApp",
    required: true,
    aliases: ["telefone", "celular", "whatsapp", "whats", "zap", "fone", "tel", "phone", "telefonecelular", "contato", "cel"],
  },
  { key: "email", label: "E-mail", required: false, aliases: ["email", "mail", "correioeletronico"] },
  {
    key: "nascimento",
    label: "Data de nascimento",
    required: false,
    aliases: ["nascimento", "datanascimento", "datadenascimento", "dtnascimento", "dtnasc", "nasc", "datanasc", "aniversario", "birthdate"],
  },
  { key: "genero", label: "Gênero", required: false, aliases: ["genero", "sexo", "gender"] },
  { key: "cep", label: "CEP", required: false, aliases: ["cep", "codigopostal", "zipcode", "zip"] },
  { key: "rua", label: "Logradouro", required: false, aliases: ["rua", "logradouro", "endereco", "street", "avenida"] },
  { key: "numero", label: "Número", required: false, aliases: ["numero", "num", "nro", "n", "no", "numerocasa", "numeroresidencia"] },
  { key: "complemento", label: "Complemento", required: false, aliases: ["complemento", "compl", "apto", "apartamento"] },
  { key: "bairro", label: "Bairro", required: false, aliases: ["bairro", "distrito", "neighborhood"] },
  { key: "cidade", label: "Cidade", required: false, aliases: ["cidade", "municipio", "city", "localidade"] },
  { key: "uf", label: "UF", required: false, aliases: ["uf", "estado", "state"] },
  { key: "zona", label: "Zona eleitoral", required: false, aliases: ["zona", "zonaeleitoral"] },
  { key: "secao", label: "Seção eleitoral", required: false, aliases: ["secao", "secaoeleitoral", "sessao", "sessaoeleitoral"] },
  { key: "apoio", label: "Nível de apoio", required: false, aliases: ["apoio", "nivelapoio", "niveldeapoio", "classificacao"] },
  { key: "tags", label: "Tags", required: false, aliases: ["tags", "tag", "etiquetas", "marcadores", "grupos", "grupo"] },
] as const;

export type ImportFieldKey = (typeof IMPORT_FIELDS)[number]["key"];
export const IMPORT_FIELD_KEYS = IMPORT_FIELDS.map((f) => f.key) as ImportFieldKey[];
/** Coluna → campo ("" = ignorar a coluna) */
export type ColumnMapping = (ImportFieldKey | "")[];
export type ImportValues = Partial<Record<ImportFieldKey, string>>;

export interface ImportRecord {
  /** Linha no arquivo original (1 = primeira linha) */
  row: number;
  values: ImportValues;
}

export type CsvSeparator = ";" | "," | "\t";

// ---------- Leitura do CSV ----------

function countOutsideQuotes(line: string, ch: string): number {
  let n = 0;
  let inQuotes = false;
  for (const c of line) {
    if (c === '"') inQuotes = !inQuotes;
    else if (c === ch && !inQuotes) n++;
  }
  return n;
}

/** Detecta o separador pela primeira linha não vazia (empate favorece ";", padrão do Excel em pt-BR) */
export function detectSeparator(text: string): CsvSeparator {
  const clean = text.replace(/^﻿/, "");
  const directive = /^sep=(.)\s*(?:\r?\n|$)/i.exec(clean);
  if (directive && [";", ",", "\t"].includes(directive[1])) return directive[1] as CsvSeparator;
  const first = clean.split(/\r\n|\n|\r/).find((l) => l.trim() !== "") ?? "";
  const counts: [CsvSeparator, number][] = [
    [";", countOutsideQuotes(first, ";")],
    [",", countOutsideQuotes(first, ",")],
    ["\t", countOutsideQuotes(first, "\t")],
  ];
  const best = counts.reduce((a, b) => (b[1] > a[1] ? b : a));
  return best[1] === 0 ? ";" : best[0];
}

/**
 * Lê CSV (RFC 4180): campos entre aspas, aspas escapadas (""), quebras de linha dentro de aspas,
 * CRLF/LF/CR, BOM e diretiva "sep=;" do Excel. Linhas totalmente vazias são descartadas.
 * Cada linha devolvida guarda o número da linha física onde começa.
 */
export function parseCsv(text: string, separator?: CsvSeparator): { separator: CsvSeparator; rows: string[][]; lines: number[] } {
  let src = text.replace(/^﻿/, "");
  const sep = separator ?? detectSeparator(src);
  let lineNo = 1;
  const directive = /^sep=.\s*(\r\n|\n|\r|$)/i.exec(src);
  if (directive) {
    src = src.slice(directive[0].length);
    lineNo = 2;
  }

  const rows: string[][] = [];
  const lines: number[] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  let rowStart = lineNo;

  const endRow = () => {
    row.push(field);
    field = "";
    if (row.some((c) => c.trim() !== "")) {
      rows.push(row);
      lines.push(rowStart);
    }
    row = [];
  };

  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (inQuotes) {
      if (c === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        if (c === "\n" || (c === "\r" && src[i + 1] !== "\n")) lineNo++;
        field += c;
      }
      continue;
    }
    if (c === '"' && field.trim() === "") {
      inQuotes = true;
      field = "";
    } else if (c === sep) {
      row.push(field);
      field = "";
    } else if (c === "\r" || c === "\n") {
      if (c === "\r" && src[i + 1] === "\n") i++;
      endRow();
      lineNo++;
      rowStart = lineNo;
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length) endRow();
  return { separator: sep, rows: rows.map((r) => r.map((c) => c.trim())), lines };
}

// ---------- Mapeamento de colunas ----------

function headerKey(header: string): string {
  return normalizeText(header).replace(/[^a-z0-9]/g, "");
}

/**
 * Associa cabeçalhos a campos: 1º por nome exato (sem acentos/pontuação), depois por "contém" (apelidos com 4+ letras).
 * Cada campo é usado no máximo uma vez.
 */
export function autoMapHeaders(headers: string[]): ColumnMapping {
  const mapping: ColumnMapping = headers.map(() => "");
  const used = new Set<ImportFieldKey>();
  const keys = headers.map(headerKey);

  keys.forEach((k, i) => {
    if (!k) return;
    const field = IMPORT_FIELDS.find((f) => !used.has(f.key) && (f.aliases as readonly string[]).includes(k));
    if (field) {
      mapping[i] = field.key;
      used.add(field.key);
    }
  });
  keys.forEach((k, i) => {
    if (!k || mapping[i]) return;
    const field = IMPORT_FIELDS.find(
      (f) => !used.has(f.key) && (f.aliases as readonly string[]).some((a) => a.length >= 4 && k.includes(a)),
    );
    if (field) {
      mapping[i] = field.key;
      used.add(field.key);
    }
  });
  return mapping;
}

export function missingRequiredFields(mapping: ColumnMapping): ImportFieldKey[] {
  return IMPORT_FIELDS.filter((f) => f.required && !mapping.includes(f.key)).map((f) => f.key);
}

/** Converte as linhas do CSV em registros {campo: valor} conforme o mapeamento */
export function buildImportRecords(
  parsed: { rows: string[][]; lines: number[] },
  mapping: ColumnMapping,
  hasHeader: boolean,
): ImportRecord[] {
  const out: ImportRecord[] = [];
  parsed.rows.forEach((cells, idx) => {
    if (hasHeader && idx === 0) return;
    const values: ImportValues = {};
    mapping.forEach((field, col) => {
      if (!field) return;
      const v = (cells[col] ?? "").trim();
      if (v) values[field] = v;
    });
    out.push({ row: parsed.lines[idx] ?? idx + 1, values });
  });
  return out;
}

// ---------- Validação de cada linha ----------

export interface ImportedVoter {
  name: string;
  phone: string;
  email: string | null;
  birthDate: Date | null;
  gender: Gender | null;
  cep: string | null;
  street: string | null;
  number: string | null;
  complement: string | null;
  neighborhood: string | null;
  city: string | null;
  state: string | null;
  electoralZone: string | null;
  electoralSection: string | null;
  supportLevel: SupportLevel | null;
  tags: string | null;
}

export interface ImportValidation {
  /** null quando a linha é inválida (nome/telefone) e será ignorada */
  voter: ImportedVoter | null;
  /** Motivos que impedem a importação da linha */
  errors: string[];
  /** Valores opcionais inválidos que serão descartados (a linha é importada sem eles) */
  warnings: string[];
}

const GENDER_ALIASES: Record<string, Gender> = {
  m: "M",
  masc: "M",
  masculino: "M",
  homem: "M",
  f: "F",
  fem: "F",
  feminino: "F",
  mulher: "F",
  o: "O",
  outro: "O",
  outros: "O",
  naobinario: "O",
  n: "N",
  ni: "N",
  naoinformado: "N",
  naoinformar: "N",
  prefereinaoinformar: "N",
  preferenaoinformar: "N",
  prefironaoinformar: "N",
};

export function normalizeGenderInput(value: string): Gender | null {
  const k = headerKey(value);
  if ((GENDERS as readonly string[]).includes(value.trim().toUpperCase())) return value.trim().toUpperCase() as Gender;
  return GENDER_ALIASES[k] ?? null;
}

const SUPPORT_ALIASES: Record<string, SupportLevel> = {
  apoiadora: "APOIADOR",
  apoiadores: "APOIADOR",
  apoia: "APOIADOR",
  simpatizantes: "SIMPATIZANTE",
  simpatica: "SIMPATIZANTE",
  simpatico: "SIMPATIZANTE",
  indecisa: "INDECISO",
  indecisos: "INDECISO",
  neutro: "INDECISO",
  neutra: "INDECISO",
  opositora: "OPOSITOR",
  opositores: "OPOSITOR",
  contra: "OPOSITOR",
};

export function normalizeSupportInput(value: string): SupportLevel | null {
  const k = headerKey(value);
  return SUPPORT_LEVELS.find((s) => headerKey(s) === k) ?? SUPPORT_ALIASES[k] ?? null;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function limited(value: string | undefined, max: number): string | null {
  const v = (value ?? "").trim().replace(/\s+/g, " ");
  return v ? v.slice(0, max) : null;
}

/** Valida e normaliza uma linha. Nome e telefone inválidos descartam a linha; demais campos inválidos viram aviso. */
export function validateImportRecord(values: ImportValues, now: Date = new Date()): ImportValidation {
  const errors: string[] = [];
  const warnings: string[] = [];

  const rawName = (values.nome ?? "").trim().replace(/\s+/g, " ");
  if (rawName.length < 3 || !hasLetter(rawName)) errors.push("Nome ausente ou muito curto");
  else if (rawName.length > 120) errors.push("Nome com mais de 120 caracteres");

  const phone = normalizeBrPhone(values.telefone ?? "");
  if (!values.telefone?.trim()) errors.push("Telefone ausente");
  else if (!phone) errors.push("Telefone inválido (use DDD + número)");

  let email: string | null = null;
  if (values.email?.trim()) {
    const e = values.email.trim().toLowerCase();
    if (EMAIL_RE.test(e) && e.length <= 160) email = e;
    else warnings.push("E-mail inválido (ignorado)");
  }

  let birthDate: Date | null = null;
  if (values.nascimento?.trim()) {
    const d = parseBirthDateInput(values.nascimento);
    const age = d ? ageFromBirthDate(d, now) : null;
    if (!d) warnings.push("Data de nascimento inválida (ignorada)");
    else if (age === null || age < MIN_VOTER_AGE || age > MAX_VOTER_AGE)
      warnings.push(`Idade fora do intervalo de ${MIN_VOTER_AGE} a ${MAX_VOTER_AGE} anos (data ignorada)`);
    else birthDate = d;
  }

  let gender: Gender | null = null;
  if (values.genero?.trim()) {
    gender = normalizeGenderInput(values.genero);
    if (!gender) warnings.push("Gênero não reconhecido (ignorado)");
  }

  let cep: string | null = null;
  if (values.cep?.trim()) {
    cep = normalizeCepInput(values.cep);
    if (!cep) warnings.push("CEP inválido (ignorado)");
  }

  let state: string | null = null;
  if (values.uf?.trim()) {
    const uf = values.uf.trim().toUpperCase();
    if ((UFS as readonly string[]).includes(uf)) state = uf;
    else warnings.push("UF inválida (ignorada)");
  }

  const digitsField = (v: string | undefined, max: number, label: string): string | null => {
    if (!v?.trim()) return null;
    const t = v.trim();
    if (!new RegExp(`^\\d{1,${max}}$`).test(t)) {
      warnings.push(`${label} inválida (ignorada)`);
      return null;
    }
    return String(Number(t));
  };

  let supportLevel: SupportLevel | null = null;
  if (values.apoio?.trim()) {
    supportLevel = normalizeSupportInput(values.apoio);
    if (!supportLevel) warnings.push("Nível de apoio não reconhecido (ignorado)");
  }

  const place = (v: string | undefined, max: number) => {
    const t = limited(v, max);
    return t ? smartCase(t) : null;
  };

  const electoralZone = digitsField(values.zona, 4, "Zona eleitoral");
  const electoralSection = digitsField(values.secao, 5, "Seção eleitoral");

  if (errors.length) return { voter: null, errors, warnings };

  return {
    voter: {
      name: titleCase(rawName),
      phone: phone!,
      email,
      birthDate,
      gender,
      cep,
      street: place(values.rua, 160),
      number: limited(values.numero, 20),
      complement: limited(values.complemento, 80),
      neighborhood: place(values.bairro, 100),
      city: place(values.cidade, 100),
      state,
      electoralZone,
      electoralSection,
      supportLevel,
      tags: serializeTags((values.tags ?? "").replace(/[|;]/g, ",").slice(0, 300)),
    },
    errors,
    warnings,
  };
}
