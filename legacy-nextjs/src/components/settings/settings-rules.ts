// Regras puras das configurações da campanha (usadas no navegador e no servidor).
// Não importe nada de servidor aqui: este arquivo é carregado por componentes cliente.
import type { FormConfig, FormFieldMode } from "@/lib/constants";

// ---------- Cor principal ----------

export const HEX_COLOR_REGEX = /^#[0-9a-f]{6}$/i;
export const DEFAULT_PRIMARY_COLOR = "#4f46e5";

export function isHexColor(value: string | null | undefined): value is string {
  return typeof value === "string" && HEX_COLOR_REGEX.test(value.trim());
}

/** "#ABCDEF" → "#abcdef"; aceita "abcdef" sem # enquanto o usuário digita. null se inválida. */
export function normalizeHexColor(value: string | null | undefined): string | null {
  if (!value) return null;
  let v = value.trim();
  if (!v.startsWith("#")) v = `#${v}`;
  return HEX_COLOR_REGEX.test(v) ? v.toLowerCase() : null;
}

/** Luminância relativa (WCAG) de uma cor #rrggbb */
export function relativeLuminance(hex: string): number {
  const n = normalizeHexColor(hex) ?? DEFAULT_PRIMARY_COLOR;
  const channel = (i: number) => {
    const c = parseInt(n.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

/** Cor de texto legível sobre o fundo informado */
export function readableTextColor(hex: string): "#ffffff" | "#0f172a" {
  const l = relativeLuminance(hex);
  // contraste com branco vs. com slate-900
  const withWhite = 1.05 / (l + 0.05);
  const withDark = (l + 0.05) / (relativeLuminance("#0f172a") + 0.05);
  return withWhite >= withDark ? "#ffffff" : "#0f172a";
}

/** Contraste WCAG entre duas cores */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

// ---------- Logo ----------

export const LOGO_MAX_BYTES = 300 * 1024;
export const LOGO_MAX_DIMENSION = 512;
export const LOGO_ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export type LogoMimeType = (typeof LOGO_ACCEPTED_TYPES)[number];
/** Tamanho máximo do arquivo original escolhido pelo usuário (antes do redimensionamento) */
export const LOGO_MAX_SOURCE_BYTES = 15 * 1024 * 1024;

const LOGO_DATA_URL_REGEX = /^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/;

export function isAcceptedLogoType(type: string): type is LogoMimeType {
  return (LOGO_ACCEPTED_TYPES as readonly string[]).includes(type);
}

/** Bytes decodificados de um conteúdo base64 (sem decodificar) */
export function base64DecodedSize(base64: string): number {
  const clean = base64.replace(/\s/g, "");
  if (!clean) return 0;
  const padding = clean.endsWith("==") ? 2 : clean.endsWith("=") ? 1 : 0;
  return Math.floor((clean.length * 3) / 4) - padding;
}

/** Bytes decodificados de uma data URL base64 (0 se não for base64) */
export function dataUrlByteSize(dataUrl: string): number {
  const i = dataUrl.indexOf(";base64,");
  if (i < 0) return 0;
  return base64DecodedSize(dataUrl.slice(i + 8));
}

function decodeBase64Prefix(base64: string, bytes: number): number[] {
  const chars = Math.ceil(bytes / 3) * 4;
  let binary: string;
  try {
    binary = atob(base64.slice(0, chars));
  } catch {
    return [];
  }
  return Array.from(binary, (ch) => ch.charCodeAt(0));
}

/** Confere a assinatura binária (magic bytes) do arquivo com o tipo declarado */
export function matchesImageSignature(mime: LogoMimeType, base64: string): boolean {
  const b = decodeBase64Prefix(base64, 12);
  if (b.length < 12) return false;
  switch (mime) {
    case "image/png":
      return b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47;
    case "image/jpeg":
      return b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff;
    case "image/webp":
      return (
        String.fromCharCode(b[0], b[1], b[2], b[3]) === "RIFF" && String.fromCharCode(b[8], b[9], b[10], b[11]) === "WEBP"
      );
  }
}

export type LogoValidation =
  | { ok: true; mime: LogoMimeType; bytes: number }
  | { ok: false; error: string };

/** Valida a data URL do logo: tipo (png/jpeg/webp), base64, assinatura e tamanho ≤ 300 KB */
export function validateLogoDataUrl(value: string, maxBytes = LOGO_MAX_BYTES): LogoValidation {
  const match = LOGO_DATA_URL_REGEX.exec(value);
  if (!match) return { ok: false, error: "Envie uma imagem PNG, JPEG ou WebP." };
  const mime = `image/${match[1]}` as LogoMimeType;
  const base64 = match[2];
  if (base64.length % 4 !== 0) return { ok: false, error: "Imagem corrompida. Tente enviar novamente." };
  const bytes = base64DecodedSize(base64);
  if (bytes === 0) return { ok: false, error: "Imagem vazia." };
  if (bytes > maxBytes) {
    return { ok: false, error: `A imagem deve ter no máximo ${Math.round(maxBytes / 1024)} KB.` };
  }
  if (!matchesImageSignature(mime, base64)) {
    return { ok: false, error: "O conteúdo do arquivo não corresponde a uma imagem válida." };
  }
  return { ok: true, mime, bytes };
}

/** Dimensões que cabem em max×max mantendo a proporção (nunca amplia) */
export function fitWithin(width: number, height: number, max: number): { width: number; height: number } {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`;
}

// ---------- Formulário público ----------

export const FORM_FIELD_MODES = ["hidden", "optional", "required"] as const satisfies readonly FormFieldMode[];

export const FORM_FIELD_MODE_LABELS: Record<FormFieldMode, string> = {
  hidden: "Oculto",
  optional: "Opcional",
  required: "Obrigatório",
};

export const FORM_FIELD_GROUPS: { key: keyof FormConfig; label: string; description: string }[] = [
  { key: "email", label: "E-mail", description: "Endereço de e-mail do eleitor." },
  { key: "birthDate", label: "Data de nascimento", description: "Permite filtrar por faixa etária." },
  { key: "gender", label: "Gênero", description: "Masculino, feminino, outro ou prefere não informar." },
  { key: "address", label: "Endereço", description: "CEP, rua, número, bairro e cidade. Alimenta o mapa por bairro." },
  { key: "electoral", label: "Zona e seção eleitoral", description: "Dados do título de eleitor." },
];

/** Limites de texto (compartilhados entre os campos do navegador e a validação do servidor) */
export const SETTINGS_LIMITS = {
  candidateName: 120,
  ballotName: 60,
  party: 40,
  city: 80,
  formTitle: 120,
  formMessage: 600,
  consentTextMin: 40,
  consentTextMax: 3000,
  privacyContact: 200,
  voterGoalMax: 10_000_000,
  electionYearMin: 2000,
  electionYearMax: 2100,
} as const;
