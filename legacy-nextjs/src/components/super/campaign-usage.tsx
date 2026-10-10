// Uso da campanha — apenas números agregados (Server Component).
import {
  BarChart3,
  CalendarClock,
  CheckCheck,
  Lock,
  MapPinned,
  MessageSquareText,
  PlugZap,
  Send,
  ShieldCheck,
  UserMinus,
  UserRoundCheck,
  Users,
  UsersRound,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProgressBar, StatCard } from "@/components/ui/misc";
import { BROADCAST_STATUS_LABELS, ROLE_LABELS, type BroadcastStatus, type CampaignRole } from "@/lib/constants";
import { formatDateTime, formatNumber, formatPercent } from "@/lib/utils";
import type { CampaignUsage } from "@/server/super/queries";

const BROADCAST_TONES: Record<BroadcastStatus, BadgeTone> = {
  DRAFT: "gray",
  SCHEDULED: "blue",
  RUNNING: "brand",
  PAUSED: "yellow",
  COMPLETED: "green",
  CANCELLED: "gray",
  FAILED: "red",
};

const ROLE_ICONS: Record<CampaignRole, LucideIcon> = {
  ADMIN: ShieldCheck,
  COORDENADOR: UserRoundCheck,
  CABO: Users,
};

const pct = (part: number, total: number) => (total > 0 ? (part / total) * 100 : 0);

function Row({ icon: Icon, label, value, hint }: { icon: LucideIcon; label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5">
      <span className="flex min-w-0 items-center gap-2 text-sm text-slate-600">
        <Icon className="size-4 shrink-0 text-slate-400" aria-hidden />
        <span className="truncate">{label}</span>
      </span>
      <span className="text-right">
        <span className="font-semibold text-slate-900 tabular-nums">{value}</span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
    </div>
  );
}

export function CampaignUsagePanel({ usage, voterGoal }: { usage: CampaignUsage; voterGoal: number | null }) {
  const teamTotal = Object.values(usage.roles).reduce((sum, r) => sum + r.active + r.inactive, 0);
  const broadcastStatuses = Object.entries(usage.broadcastsByStatus).filter(([, n]) => n > 0);

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <Lock className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
        <p>
          Somente números agregados. Por privacidade (LGPD), nomes, telefones e endereços de eleitores não ficam visíveis para o super
          admin.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Eleitores cadastrados" value={formatNumber(usage.voters)} icon={UsersRound} />
        <StatCard
          label="Últimos 7 dias"
          value={formatNumber(usage.voters7)}
          hint={`${formatNumber(usage.voters30)} nos últimos 30 dias`}
          icon={CalendarClock}
          tone="blue"
        />
        <StatCard
          label="Aptos a receber WhatsApp"
          value={formatNumber(usage.messageable)}
          hint={`${formatPercent(pct(usage.messageable, usage.voters))} dos cadastros (consentimento + opt-in)`}
          icon={CheckCheck}
          tone="green"
        />
        <StatCard
          label="Mensagens enviadas"
          value={formatNumber(usage.messagesSent)}
          hint={usage.messagesFailed > 0 ? `${formatNumber(usage.messagesFailed)} com falha` : "Nenhuma falha registrada"}
          icon={Send}
          tone="purple"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Equipe</CardTitle>
            <CardDescription>{formatNumber(teamTotal)} usuários na campanha</CardDescription>
          </CardHeader>
          <CardContent className="divide-y divide-slate-100 py-1">
            {(Object.keys(usage.roles) as CampaignRole[]).map((role) => {
              const r = usage.roles[role];
              return (
                <Row
                  key={role}
                  icon={ROLE_ICONS[role]}
                  label={ROLE_LABELS[role]}
                  value={formatNumber(r.active)}
                  hint={r.inactive > 0 ? `+ ${formatNumber(r.inactive)} desativado(s)` : undefined}
                />
              );
            })}
            <Row icon={CalendarClock} label="Último acesso da equipe" value={usage.lastLoginAt ? formatDateTime(usage.lastLoginAt) : "—"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Eleitores</CardTitle>
            <CardDescription>Cadastros, consentimento e mapa</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 py-1">
            {voterGoal ? (
              <div className="space-y-2 py-2.5">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-600">Meta de cadastros</span>
                  <span className="font-semibold text-slate-900 tabular-nums">
                    {formatNumber(usage.voters)} / {formatNumber(voterGoal)}
                  </span>
                </div>
                <ProgressBar value={usage.voters} max={voterGoal} tone={usage.voters >= voterGoal ? "green" : "brand"} />
                <p className="text-xs text-slate-500">{formatPercent(pct(usage.voters, voterGoal))} da meta</p>
              </div>
            ) : (
              <p className="py-2.5 text-sm text-slate-500">Sem meta de cadastros definida.</p>
            )}
            <div className="divide-y divide-slate-100 border-t border-slate-100">
              <Row icon={CalendarClock} label="Últimos 30 dias" value={formatNumber(usage.voters30)} />
              <Row
                icon={MapPinned}
                label="Localizados no mapa"
                value={formatNumber(usage.geolocated)}
                hint={formatPercent(pct(usage.geolocated, usage.voters))}
              />
              <Row icon={UserMinus} label="Descadastrados do WhatsApp" value={formatNumber(usage.optedOut)} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>WhatsApp e recursos</CardTitle>
            <CardDescription>Conexões, modelos e disparos</CardDescription>
          </CardHeader>
          <CardContent className="divide-y divide-slate-100 py-1">
            <Row
              icon={PlugZap}
              label="Conexões de API"
              value={formatNumber(usage.connections)}
              hint={usage.connections > 0 ? `${formatNumber(usage.connectedConnections)} conectada(s)` : undefined}
            />
            <Row icon={MessageSquareText} label="Modelos de mensagem" value={formatNumber(usage.templates)} />
            <Row icon={Send} label="Disparos" value={formatNumber(usage.broadcasts)} />
            <Row icon={XCircle} label="Mensagens com falha" value={formatNumber(usage.messagesFailed)} />
            <Row icon={BarChart3} label="Dashboards" value={formatNumber(usage.dashboards)} />
            {broadcastStatuses.length > 0 && (
              <div className="flex flex-wrap gap-1.5 py-3">
                {broadcastStatuses.map(([status, n]) => (
                  <Badge key={status} tone={BROADCAST_TONES[status as BroadcastStatus] ?? "gray"}>
                    {BROADCAST_STATUS_LABELS[status as BroadcastStatus] ?? status}: {formatNumber(n)}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
