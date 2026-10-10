import Link from "next/link";
import { Mail } from "lucide-react";
import { Logo } from "@/components/layout/logo";

export const CONTACT_EMAIL = "contato@efind.com.br";

/** Rodapé das páginas públicas (landing, privacidade e termos) */
export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr] lg:px-8">
        <div className="space-y-3">
          <Link href="/" aria-label="E-Find — página inicial">
            <Logo />
          </Link>
          <p className="max-w-sm text-sm text-slate-500">
            Gestão de campanha eleitoral: cadastro de eleitores com consentimento, equipe hierárquica, mapa por bairro e
            WhatsApp oficial.
          </p>
        </div>
        <nav aria-label="Institucional" className="space-y-2 text-sm">
          <p className="font-semibold text-slate-900">Institucional</p>
          <ul className="space-y-2 text-slate-600">
            <li>
              <Link href="/privacidade" className="hover:text-brand-700">
                Política de privacidade
              </Link>
            </li>
            <li>
              <Link href="/termos" className="hover:text-brand-700">
                Termos de uso
              </Link>
            </li>
            <li>
              <Link href="/login" className="hover:text-brand-700">
                Acessar painel
              </Link>
            </li>
          </ul>
        </nav>
        <div className="space-y-2 text-sm">
          <p className="font-semibold text-slate-900">Contato</p>
          <a href={`mailto:${CONTACT_EMAIL}`} className="inline-flex items-center gap-2 text-slate-600 hover:text-brand-700">
            <Mail className="size-4" aria-hidden /> {CONTACT_EMAIL}
          </a>
          <p className="text-xs text-slate-500">Titulares de dados: veja como exercer seus direitos na política de privacidade.</p>
        </div>
      </div>
      <div className="border-t border-slate-100">
        <p className="mx-auto max-w-6xl px-4 py-5 text-xs text-slate-500 sm:px-6 lg:px-8">
          © {year} E-Find · efind.com.br · Todos os direitos reservados.
        </p>
      </div>
    </footer>
  );
}
