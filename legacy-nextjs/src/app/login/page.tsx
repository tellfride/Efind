import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { CheckCircle2, MapPinned, QrCode, Send } from "lucide-react";
import { getSessionUser, homePathFor } from "@/lib/auth";
import { Logo } from "@/components/layout/logo";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Entrar" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const user = await getSessionUser();
  if (user) redirect(homePathFor(user.role));
  const { next } = await searchParams;

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-slate-900 lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, rgba(99,102,241,.45), transparent 40%), radial-gradient(circle at 80% 70%, rgba(37,211,102,.25), transparent 45%)",
          }}
        />
        <Logo className="relative text-white" />
        <div className="relative max-w-md">
          <h1 className="text-4xl leading-tight font-bold text-white">Sua campanha organizada, do cabo eleitoral ao candidato.</h1>
          <ul className="mt-8 space-y-4 text-slate-300">
            {[
              { icon: QrCode, text: "Cadastro de eleitores por link e QR Code, vinculado a quem cadastrou" },
              { icon: MapPinned, text: "Mapa por bairro a partir do CEP, com filtros" },
              { icon: Send, text: "Disparos de WhatsApp para quem consentiu, com modelos de mensagem" },
              { icon: CheckCircle2, text: "Permissões por nível: administrador, coordenador e cabo eleitoral" },
            ].map(({ icon: Icon, text }) => (
              <li key={text} className="flex gap-3">
                <Icon className="mt-0.5 size-5 shrink-0 text-brand-400" />
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-slate-500">© {new Date().getFullYear()} E-Find · efind.com.br</p>
      </div>

      <div className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h2 className="text-2xl font-bold text-slate-900">Entrar no painel</h2>
          <p className="mt-1 text-sm text-slate-500">Use o e-mail e a senha fornecidos pela sua coordenação.</p>
          <LoginForm next={next} />
        </div>
      </div>
    </div>
  );
}
