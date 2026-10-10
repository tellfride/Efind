import { MapPin, QrCode, TrendingUp, UsersRound } from "lucide-react";

// Ilustração do painel feita só com HTML/CSS (sem imagens externas). Puramente decorativa.

const BARS = [32, 44, 38, 52, 61, 58, 72, 69, 84, 78, 92, 100];

const DOTS = [
  { top: "22%", left: "18%", size: 34, tone: "bg-brand-400/50" },
  { top: "30%", left: "52%", size: 48, tone: "bg-brand-500/50" },
  { top: "58%", left: "30%", size: 40, tone: "bg-emerald-400/50" },
  { top: "64%", left: "68%", size: 28, tone: "bg-amber-400/60" },
  { top: "42%", left: "78%", size: 22, tone: "bg-brand-300/60" },
  { top: "76%", left: "12%", size: 18, tone: "bg-emerald-300/60" },
];

const TEAM = [
  { label: "Equipe Centro", pct: 92 },
  { label: "Equipe Norte", pct: 74 },
  { label: "Equipe Leste", pct: 58 },
];

export function MockDashboard() {
  return (
    <div aria-hidden className="relative select-none">
      <div className="overflow-hidden rounded-2xl border border-white/10 bg-white shadow-2xl shadow-brand-950/40 ring-1 ring-white/10">
        {/* barra do navegador */}
        <div className="flex items-center gap-1.5 border-b border-slate-200 bg-slate-100 px-3 py-2">
          <span className="size-2.5 rounded-full bg-red-400" />
          <span className="size-2.5 rounded-full bg-amber-400" />
          <span className="size-2.5 rounded-full bg-emerald-400" />
          <span className="ml-3 h-4 flex-1 rounded bg-white text-[9px] leading-4 text-slate-400 sm:max-w-56">
            &nbsp;efind.com.br/painel
          </span>
        </div>

        <div className="flex">
          {/* menu lateral */}
          <div className="hidden w-28 shrink-0 space-y-2 bg-slate-900 p-3 sm:block">
            <div className="mb-4 flex items-center gap-1.5">
              <span className="size-4 rounded bg-brand-500" />
              <span className="h-2 w-12 rounded bg-white/70" />
            </div>
            {[true, false, false, false, false, false].map((active, i) => (
              <div key={i} className={`h-5 rounded ${active ? "bg-brand-600" : "bg-white/5"}`} />
            ))}
          </div>

          <div className="min-w-0 flex-1 space-y-3 bg-slate-50 p-3 sm:p-4">
            {/* indicadores */}
            <div className="grid grid-cols-3 gap-2">
              {[
                { icon: UsersRound, label: "Eleitores", value: "12.480", tone: "text-brand-600 bg-brand-50" },
                { icon: TrendingUp, label: "Hoje", value: "+326", tone: "text-emerald-600 bg-emerald-50" },
                { icon: QrCode, label: "Via QR", value: "64%", tone: "text-amber-600 bg-amber-50" },
              ].map(({ icon: Icon, label, value, tone }) => (
                <div key={label} className="rounded-lg border border-slate-200 bg-white p-2 sm:p-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[9px] font-medium text-slate-500 sm:text-[10px]">{label}</span>
                    <span className={`hidden size-5 items-center justify-center rounded sm:flex ${tone}`}>
                      <Icon className="size-3" />
                    </span>
                  </div>
                  <p className="mt-1 text-sm font-bold text-slate-900 tabular-nums sm:text-base">{value}</p>
                </div>
              ))}
            </div>

            <div className="grid gap-2 sm:grid-cols-5">
              {/* gráfico de barras */}
              <div className="rounded-lg border border-slate-200 bg-white p-2.5 sm:col-span-3">
                <p className="text-[10px] font-semibold text-slate-700">Cadastros por semana</p>
                <div className="mt-2 flex h-20 items-end gap-1 sm:h-24">
                  {BARS.map((h, i) => (
                    <div
                      key={i}
                      className={`flex-1 rounded-t ${i === BARS.length - 1 ? "bg-brand-600" : "bg-brand-200"}`}
                      style={{ height: `${h}%` }}
                    />
                  ))}
                </div>
              </div>

              {/* mapa por bairro */}
              <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-white sm:col-span-2">
                <div
                  className="absolute inset-0"
                  style={{
                    backgroundColor: "#eef2f7",
                    backgroundImage:
                      "linear-gradient(115deg, transparent 46%, #ffffff 46%, #ffffff 50%, transparent 50%), linear-gradient(25deg, transparent 60%, #ffffff 60%, #ffffff 63%, transparent 63%), linear-gradient(#e2e8f0 1px, transparent 1px), linear-gradient(90deg, #e2e8f0 1px, transparent 1px)",
                    backgroundSize: "100% 100%, 100% 100%, 18px 18px, 18px 18px",
                  }}
                />
                {DOTS.map((d, i) => (
                  <span
                    key={i}
                    className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full ${d.tone} ring-2 ring-white/60`}
                    style={{ top: d.top, left: d.left, width: d.size, height: d.size }}
                  />
                ))}
                <span className="absolute top-[30%] left-[52%] -translate-x-1/2 -translate-y-full text-brand-700">
                  <MapPin className="size-5 fill-white" />
                </span>
                <span className="absolute top-2 left-2 rounded bg-white/90 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700 shadow-sm">
                  Mapa por bairro
                </span>
                <div className="h-28 sm:h-full" />
              </div>
            </div>

            {/* ranking */}
            <div className="rounded-lg border border-slate-200 bg-white p-2.5">
              <p className="text-[10px] font-semibold text-slate-700">Metas da equipe</p>
              <div className="mt-2 space-y-1.5">
                {TEAM.map((t) => (
                  <div key={t.label} className="flex items-center gap-2">
                    <span className="w-20 shrink-0 truncate text-[10px] text-slate-500">{t.label}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full bg-emerald-500" style={{ width: `${t.pct}%` }} />
                    </div>
                    <span className="w-7 text-right text-[10px] font-semibold text-slate-600 tabular-nums">{t.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* cartão flutuante: notificação de novo cadastro */}
      <div className="absolute -bottom-5 -left-2 hidden w-60 rounded-xl border border-slate-200 bg-white p-3 shadow-xl sm:block lg:-left-8">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
            <QrCode className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-900">Novo cadastro via QR Code</p>
            <p className="truncate text-[11px] text-slate-500">Bairro Centro · vinculado ao cabo eleitoral</p>
          </div>
        </div>
      </div>
    </div>
  );
}
