// Telefones brasileiros. Armazenamos sempre só dígitos com DDI 55: 55 + DDD (2) + número (8 ou 9).

const VALID_DDDS = new Set([
  11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46,
  47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85,
  86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
]);

/**
 * Normaliza para "55DDNNNNNNNNN". Aceita "(11) 98765-4321", "+55 11 98765 4321", "011987654321"...
 * Retorna null se não for um telefone brasileiro válido.
 */
export function normalizeBrPhone(input: string | null | undefined): string | null {
  if (!input) return null;
  let d = input.replace(/\D/g, "");
  if (d.startsWith("00")) d = d.slice(2); // prefixo internacional 00 55 ...
  else if (d.startsWith("0") && (d.length === 11 || d.length === 12)) d = d.slice(1); // 0 + DDD + número
  if (d.length === 12 || d.length === 13) {
    if (!d.startsWith("55")) return null;
    d = d.slice(2);
  }
  if (d.length !== 10 && d.length !== 11) return null;
  const ddd = Number(d.slice(0, 2));
  if (!VALID_DDDS.has(ddd)) return null;
  const number = d.slice(2);
  if (number.length === 9 && number[0] !== "9") return null; // celular tem 9 dígitos começando com 9
  if (number.length === 8 && !/[2-9]/.test(number[0])) return null;
  return `55${d}`;
}

export function isValidBrPhone(input: string | null | undefined): boolean {
  return normalizeBrPhone(input) !== null;
}

/** Formata "5511987654321" → "(11) 98765-4321" */
export function formatPhone(stored: string | null | undefined): string {
  if (!stored) return "";
  const d = stored.replace(/\D/g, "").replace(/^55(?=\d{10,11}$)/, "");
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return stored;
}

/** Máscara progressiva para inputs: "11987" → "(11) 987" */
export function maskPhoneInput(value: string): string {
  const d = value.replace(/\D/g, "").slice(0, 11);
  if (d.length <= 2) return d.length ? `(${d}` : "";
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
}

/** Link wa.me para abrir conversa */
export function whatsappLink(stored: string, text?: string): string {
  const base = `https://wa.me/${stored.replace(/\D/g, "")}`;
  return text ? `${base}?text=${encodeURIComponent(text)}` : base;
}
