// Links de cadastro e QR Codes (servidor).
import QRCode from "qrcode";
import { appUrl } from "./env";

export type RegistrationSource = "link" | "qr";

/** URL pública do formulário de cadastro de um usuário (QR Codes usam ?src=qr para medir a origem) */
export function registrationUrl(inviteCode: string, source: RegistrationSource = "link"): string {
  return appUrl(`/c/${inviteCode}${source === "qr" ? "?src=qr" : ""}`);
}

/** QR Code como data URL PNG */
export async function qrDataUrl(text: string, opts: { size?: number; color?: string } = {}): Promise<string> {
  return QRCode.toDataURL(text, {
    errorCorrectionLevel: "M",
    margin: 2,
    width: opts.size ?? 512,
    color: { dark: opts.color ?? "#0f172a", light: "#ffffff" },
  });
}

/** QR Code como SVG (string) — nítido para impressão */
export async function qrSvg(text: string, opts: { color?: string } = {}): Promise<string> {
  return QRCode.toString(text, {
    type: "svg",
    errorCorrectionLevel: "M",
    margin: 2,
    color: { dark: opts.color ?? "#0f172a", light: "#ffffff" },
  });
}
