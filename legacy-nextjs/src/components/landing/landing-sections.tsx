import Link from "next/link";
import {
  ArrowRight,
  BadgeCheck,
  ClipboardCheck,
  Crown,
  FileLock2,
  History,
  LayoutDashboard,
  Lock,
  Mail,
  MapPinned,
  MessageSquareText,
  Network,
  QrCode,
  Scale,
  ShieldCheck,
  Smartphone,
  UserPlus,
  UserRoundCog,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { Logo } from "@/components/layout/logo";
import { cn } from "@/lib/utils";
import { MockDashboard } from "./mock-dashboard";
import { CONTACT_EMAIL } from "./site-footer";

export interface LandingCta {
  href: string;
  label: string;
}

const primaryCls =
  "inline-flex h-12 items-center justify-center gap-2 rounded-lg bg-brand-600 px-6 text-base font-semibold text-white shadow-lg shadow-brand-900/30 transition-colors hover:bg-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950";
const secondaryDarkCls =
  "inline-flex h-12 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/5 px-6 text-base font-semibold text-white transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50";

function SectionHeading({ eyebrow, title, description, dark }: { eyebrow: string; title: string; description?: string; dark?: boolean }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className={cn("text-sm font-semibold tracking-wide uppercase", dark ? "text-brand-300" : "text-brand-600")}>{eyebrow}</p>
      <h2 className={cn("mt-2 text-3xl font-bold tracking-tight sm:text-4xl", dark ? "text-white" : "text-slate-900")}>{title}</h2>
      {description && <p className={cn("mt-4 text-base sm:text-lg", dark ? "text-slate-300" : "text-slate-600")}>{description}</p>}
    </div>
  );
}

// ---------------- Cabeçalho ----------------

export function LandingHeader({ cta }: { cta: LandingCta }) {
  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-slate-950/80 backdrop-blur supports-[backdrop-filter]:bg-slate-950/70">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6 lg:px-8">
        <Link href="/" aria-label="E-Find — página inicial">
          <Logo className="text-white" />
        </Link>
        <nav aria-label="Seções" className="hidden flex-1 items-center gap-6 text-sm font-medium text-slate-300 md:flex">
          <a href="#como-funciona" className="hover:text-white">
            Como funciona
          </a>
          <a href="#recursos" className="hover:text-white">
            Recursos
          </a>
          <a href="#seguranca" className="hover:text-white">
            Segurança e conformidade
          </a>
        </nav>
        <div className="ml-auto md:ml-0">
          <Link
            href={cta.href}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-white px-3.5 text-sm font-semibold text-slate-900 transition-colors hover:bg-brand-50"
          >
            {cta.label} <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      </div>
    </header>
  );
}

// ---------------- Hero ----------------

export function Hero({ cta }: { cta: LandingCta }) {
  return (
    <section className="relative overflow-hidden bg-slate-950">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(60rem 30rem at 10% -10%, rgba(99,102,241,.35), transparent 60%), radial-gradient(40rem 26rem at 95% 20%, rgba(37,211,102,.16), transparent 60%), radial-gradient(50rem 30rem at 50% 120%, rgba(79,70,229,.30), transparent 60%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage: "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)",
          backgroundSize: "48px 48px",
          maskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
        }}
      />
      <div className="relative mx-auto grid max-w-6xl items-center gap-14 px-4 pt-14 pb-24 sm:px-6 sm:pt-20 lg:grid-cols-[1.05fr_1fr] lg:px-8 lg:pt-24 lg:pb-32">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium text-brand-200">
            <ShieldCheck className="size-3.5" aria-hidden /> Em conformidade com a LGPD e as regras do TSE
          </p>
          <h1 className="mt-6 text-4xl leading-[1.08] font-extrabold tracking-tight text-white sm:text-5xl lg:text-6xl">
            Organize sua campanha <span className="bg-gradient-to-r from-brand-300 to-emerald-300 bg-clip-text text-transparent">do cabo eleitoral ao candidato</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-300">
            Cadastro de eleitores por link e QR Code, equipe com hierarquia e permissões, mapa por bairro a partir do CEP e
            comunicação pelo WhatsApp oficial — tudo em um só painel, pensado para o celular de quem está na rua.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href={cta.href} className={primaryCls}>
              {cta.label} <ArrowRight className="size-5" aria-hidden />
            </Link>
            <a href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Quero conhecer o E-Find")}`} className={secondaryDarkCls}>
              <Mail className="size-5" aria-hidden /> Fale conosco
            </a>
          </div>
          <ul className="mt-10 grid gap-3 text-sm text-slate-300 sm:grid-cols-3">
            {[
              { icon: Lock, text: "Campanhas isoladas" },
              { icon: BadgeCheck, text: "API oficial do WhatsApp" },
              { icon: ClipboardCheck, text: "Consentimento registrado" },
            ].map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-2">
                <Icon className="size-4 shrink-0 text-emerald-300" aria-hidden />
                {text}
              </li>
            ))}
          </ul>
        </div>
        <div className="relative mx-auto w-full max-w-xl lg:max-w-none">
          <MockDashboard />
          <p className="sr-only">Ilustração do painel do E-Find com indicadores, gráfico de cadastros, mapa por bairro e metas da equipe.</p>
        </div>
      </div>
    </section>
  );
}

// ---------------- Como funciona ----------------

const STEPS: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: UserPlus,
    title: "Cadastre a equipe",
    text: "O administrador cria coordenadores e cabos eleitorais e define o que cada nível pode ver e fazer.",
  },
  {
    icon: QrCode,
    title: "Cada cabo recebe seu link e QR Code",
    text: "Link pessoal e cartaz com QR Code para imprimir ou compartilhar. Todo cadastro fica vinculado a quem divulgou.",
  },
  {
    icon: Smartphone,
    title: "Eleitores se cadastram",
    text: "Formulário rápido no celular: o CEP preenche o endereço e o consentimento LGPD é registrado com data e hora.",
  },
  {
    icon: MapPinned,
    title: "Acompanhe no mapa e nos dashboards",
    text: "Veja onde estão seus apoiadores por bairro, o desempenho de cada cabo e a evolução das metas.",
  },
  {
    icon: MessageSquareText,
    title: "Comunique-se pelo WhatsApp oficial",
    text: "Modelos de mensagem com variáveis e disparos segmentados somente para quem aceitou receber.",
  },
];

export function HowItWorks() {
  return (
    <section id="como-funciona" className="scroll-mt-16 bg-white py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="Como funciona"
          title="Da rua ao painel em cinco passos"
          description="Cada pessoa da equipe trabalha com o próprio link. Você acompanha tudo em tempo real, por bairro e por equipe."
        />
        <ol className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((step, i) => (
            <li key={step.title} className="relative rounded-2xl border border-slate-200 bg-slate-50/60 p-5">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
                  <step.icon className="size-5" aria-hidden />
                </span>
                <span className="text-sm font-bold text-brand-600 tabular-nums">0{i + 1}</span>
              </div>
              <h3 className="mt-4 text-base font-semibold text-slate-900">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{step.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ---------------- Recursos ----------------

const FEATURES: { icon: LucideIcon; title: string; text: string; tone: string }[] = [
  {
    icon: Network,
    title: "Hierarquia e permissões",
    text: "Administrador, coordenador e cabo eleitoral: cada um vê apenas a própria rede, com permissões por módulo definidas pelo administrador.",
    tone: "bg-brand-50 text-brand-600",
  },
  {
    icon: QrCode,
    title: "Cadastro por QR Code",
    text: "Link e QR Code individuais, cartaz pronto para imprimir e a origem de cada cadastro registrada automaticamente.",
    tone: "bg-amber-50 text-amber-600",
  },
  {
    icon: MapPinned,
    title: "Mapa por bairro via CEP",
    text: "O CEP vira ponto no mapa. Filtre por bairro, cidade, cabo eleitoral e nível de apoio para planejar a ação de rua.",
    tone: "bg-emerald-50 text-emerald-600",
  },
  {
    icon: LayoutDashboard,
    title: "Dashboards personalizáveis",
    text: "Monte painéis com os indicadores que importam: ranking da equipe, metas, crescimento diário e distribuição territorial.",
    tone: "bg-sky-50 text-sky-600",
  },
  {
    icon: MessageSquareText,
    title: "Disparos de WhatsApp com modelos",
    text: "Modelos com variáveis como nome e bairro, público segmentado por filtros e acompanhamento de entrega e leitura.",
    tone: "bg-green-50 text-green-600",
  },
  {
    icon: History,
    title: "Auditoria completa",
    text: "Logins, alterações, exportações e disparos ficam registrados para a campanha prestar contas com segurança.",
    tone: "bg-violet-50 text-violet-600",
  },
];

export function Features() {
  return (
    <section id="recursos" className="scroll-mt-16 bg-slate-50 py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="Recursos"
          title="Tudo o que a campanha precisa, sem planilhas soltas"
          description="Ferramentas simples para a equipe de campo e visão estratégica para a coordenação."
        />
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md">
              <span className={cn("flex size-11 items-center justify-center rounded-xl", f.tone)}>
                <f.icon className="size-5" aria-hidden />
              </span>
              <h3 className="mt-5 text-lg font-semibold text-slate-900">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{f.text}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ---------------- Níveis de acesso ----------------

const ROLES: { icon: LucideIcon; title: string; subtitle: string; items: string[] }[] = [
  {
    icon: Crown,
    title: "Administrador",
    subtitle: "Candidato e coordenação geral",
    items: ["Visão completa da campanha", "Define as permissões de cada nível", "Configura identidade, formulário e WhatsApp"],
  },
  {
    icon: UserRoundCog,
    title: "Coordenador",
    subtitle: "Líder de região ou equipe",
    items: ["Acompanha os próprios cabos eleitorais", "Metas e mapa da sua rede", "Cadastra novos cabos abaixo de si"],
  },
  {
    icon: UsersRound,
    title: "Cabo eleitoral",
    subtitle: "Quem está na rua",
    items: ["Link e QR Code no celular", "Vê apenas os próprios cadastros", "Cadastro manual em campo"],
  },
];

export function Roles() {
  return (
    <section className="bg-white py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="Para cada nível da campanha"
          title="Cada pessoa vê exatamente o que precisa"
          description="O super admin do E-Find cria a campanha do candidato e, a partir daí, a própria campanha organiza sua equipe."
        />
        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {ROLES.map((r, i) => (
            <div key={r.title} className="relative rounded-2xl border border-slate-200 p-6">
              {i < ROLES.length - 1 && (
                <ArrowRight className="absolute top-1/2 -right-5 hidden size-4 -translate-y-1/2 text-slate-300 md:block" aria-hidden />
              )}
              <div className="flex items-center gap-3">
                <span className="flex size-11 items-center justify-center rounded-xl bg-slate-900 text-white">
                  <r.icon className="size-5" aria-hidden />
                </span>
                <div>
                  <h3 className="text-lg font-semibold text-slate-900">{r.title}</h3>
                  <p className="text-sm text-slate-500">{r.subtitle}</p>
                </div>
              </div>
              <ul className="mt-5 space-y-2.5 text-sm text-slate-600">
                {r.items.map((item) => (
                  <li key={item} className="flex gap-2">
                    <BadgeCheck className="mt-0.5 size-4 shrink-0 text-brand-600" aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mx-auto mt-10 flex max-w-2xl items-center justify-center gap-2 rounded-xl bg-slate-50 px-4 py-3 text-center text-sm text-slate-600">
          <Lock className="size-4 shrink-0 text-brand-600" aria-hidden />
          Isolamento total: nenhum candidato enxerga os dados da campanha de outro.
        </p>
      </div>
    </section>
  );
}

// ---------------- Segurança e conformidade ----------------

const LGPD_ITEMS = [
  "Consentimento explícito, com data, hora e texto aceito registrados",
  "Aceite de mensagens de WhatsApp separado e opcional",
  "Descadastro a qualquer momento — basta responder SAIR",
  "Isolamento entre campanhas e acesso limitado pela hierarquia",
  "Senhas protegidas por hash e credenciais de API criptografadas",
  "Trilha de auditoria de acessos, alterações e exportações",
];

const TSE_ITEMS = [
  "Somente a API oficial do WhatsApp (Meta) e parceiros oficiais",
  "Envio apenas para eleitores que consentiram — sem listas compradas",
  "Mecanismo de descadastramento em toda comunicação (Lei nº 9.504/1997, art. 57-G)",
  "Sem disparadores não oficiais, chips descartáveis ou WhatsApp Web automatizado",
];

export function Compliance() {
  return (
    <section id="seguranca" className="relative scroll-mt-16 overflow-hidden bg-slate-950 py-20 sm:py-24">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ backgroundImage: "radial-gradient(40rem 24rem at 85% 0%, rgba(99,102,241,.25), transparent 60%)" }}
      />
      <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          dark
          eyebrow="Segurança e conformidade"
          title="Feito para respeitar o eleitor e a legislação eleitoral"
          description="Comunicação política responsável protege a campanha. O E-Find foi desenhado com a LGPD e as resoluções do TSE como ponto de partida."
        />
        <div className="mt-14 grid gap-6 lg:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-6 sm:p-8">
            <div className="flex items-center gap-3">
              <span className="flex size-11 items-center justify-center rounded-xl bg-brand-500/20 text-brand-200">
                <FileLock2 className="size-5" aria-hidden />
              </span>
              <div>
                <h3 className="text-lg font-semibold text-white">LGPD</h3>
                <p className="text-sm text-slate-400">Lei nº 13.709/2018</p>
              </div>
            </div>
            <ul className="mt-6 space-y-3 text-sm text-slate-300">
              {LGPD_ITEMS.map((item) => (
                <li key={item} className="flex gap-2.5">
                  <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-300" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-6 sm:p-8">
            <div className="flex items-center gap-3">
              <span className="flex size-11 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-200">
                <Scale className="size-5" aria-hidden />
              </span>
              <div>
                <h3 className="text-lg font-semibold text-white">Justiça Eleitoral</h3>
                <p className="text-sm text-slate-400">Lei das Eleições e resoluções do TSE</p>
              </div>
            </div>
            <ul className="mt-6 space-y-3 text-sm text-slate-300">
              {TSE_ITEMS.map((item) => (
                <li key={item} className="flex gap-2.5">
                  <BadgeCheck className="mt-0.5 size-4 shrink-0 text-emerald-300" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
            <p className="mt-6 rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400">
              A responsabilidade pelo conteúdo e pelo período de propaganda é da campanha. Veja os{" "}
              <Link href="/termos" className="font-medium text-brand-200 underline-offset-2 hover:underline">
                termos de uso
              </Link>
              .
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

// ---------------- Chamada final ----------------

export function FinalCta({ cta }: { cta: LandingCta }) {
  return (
    <section className="bg-white py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="relative overflow-hidden rounded-3xl bg-brand-600 px-6 py-12 text-center shadow-xl sm:px-12 sm:py-16">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage:
                "radial-gradient(30rem 16rem at 0% 0%, rgba(255,255,255,.18), transparent 60%), radial-gradient(30rem 16rem at 100% 100%, rgba(37,211,102,.25), transparent 60%)",
            }}
          />
          <div className="relative">
            <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Pronto para organizar sua campanha?</h2>
            <p className="mx-auto mt-4 max-w-xl text-base text-brand-100 sm:text-lg">
              Fale com a gente para criar o ambiente do seu candidato ou acesse o painel com o login enviado pela coordenação.
            </p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <Link
                href={cta.href}
                className="inline-flex h-12 items-center justify-center gap-2 rounded-lg bg-white px-6 text-base font-semibold text-brand-700 shadow-sm transition-colors hover:bg-brand-50"
              >
                {cta.label} <ArrowRight className="size-5" aria-hidden />
              </Link>
              <a
                href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Quero conhecer o E-Find")}`}
                className="inline-flex h-12 items-center justify-center gap-2 rounded-lg border border-white/30 px-6 text-base font-semibold text-white transition-colors hover:bg-white/10"
              >
                <Mail className="size-5" aria-hidden /> {CONTACT_EMAIL}
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
