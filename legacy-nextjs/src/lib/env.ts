// Acesso centralizado às variáveis de ambiente.

function required(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Variável de ambiente ${name} não configurada (veja .env.example)`);
  return v;
}

export const env = {
  get sessionSecret() {
    const s = required("SESSION_SECRET");
    if (s.length < 32) throw new Error("SESSION_SECRET deve ter pelo menos 32 caracteres");
    return s;
  },
  get encryptionKey() {
    return required("ENCRYPTION_KEY");
  },
  get cronSecret() {
    return process.env.CRON_SECRET ?? "";
  },
  get appUrl() {
    return (process.env.APP_URL ?? process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000").replace(/\/+$/, "");
  },
  get geocoderUserAgent() {
    return process.env.GEOCODER_USER_AGENT ?? "E-Find/1.0 (contato@efind.com.br)";
  },
  get isProduction() {
    return process.env.NODE_ENV === "production";
  },
};

/** URL pública absoluta para um caminho (ex.: appUrl("/c/abc")) */
export function appUrl(path = "/"): string {
  return `${env.appUrl}${path.startsWith("/") ? path : `/${path}`}`;
}
