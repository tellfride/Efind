import { Badge, type BadgeTone } from "@/components/ui/badge";
import { ROLE_LABELS, type CampaignRole } from "@/lib/constants";

const ROLE_TONES: Record<CampaignRole, BadgeTone> = {
  ADMIN: "purple",
  COORDENADOR: "blue",
  CABO: "green",
};

/** Selo do papel na campanha (Administrador, Coordenador, Cabo eleitoral) */
export function RoleBadge({ role, className }: { role: CampaignRole; className?: string }) {
  return (
    <Badge tone={ROLE_TONES[role]} className={className}>
      {ROLE_LABELS[role]}
    </Badge>
  );
}

/** Selo de status (exibido só para inativos, por padrão) */
export function StatusBadge({ active, showActive = false }: { active: boolean; showActive?: boolean }) {
  if (active) return showActive ? <Badge tone="green">Ativo</Badge> : null;
  return <Badge tone="gray">Inativo</Badge>;
}
