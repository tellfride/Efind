// Dashboards-modelo. Contrato: createDefaultDashboards(tx, campaignId) é chamado por bootstrapCampaign
// (criação da campanha e seed). Os modelos também servem de ponto de partida em "Novo dashboard".
import type { Prisma } from "@prisma/client";
import type { DashboardWidget } from "@/lib/dashboard-types";

export const DASHBOARD_PRESET_KEYS = ["visao_geral", "equipe", "territorial", "comunicacao"] as const;
export type DashboardPresetKey = (typeof DASHBOARD_PRESET_KEYS)[number];

export interface DashboardPreset {
  key: DashboardPresetKey;
  name: string;
  description: string;
  widgets: DashboardWidget[];
}

export const DASHBOARD_PRESETS: Record<DashboardPresetKey, DashboardPreset> = {
  visao_geral: {
    key: "visao_geral",
    name: "Visão geral",
    description: "Principais números da campanha e o ranking de cadastros por cabo eleitoral.",
    widgets: [
      { id: "vg-total", type: "kpi_total", size: "sm", config: {} },
      { id: "vg-hoje", type: "kpi_today", size: "sm", config: {} },
      { id: "vg-periodo", type: "kpi_period", size: "sm", config: { period: 30 } },
      { id: "vg-meta", type: "kpi_goal", size: "sm", config: {} },
      { id: "vg-ranking", type: "ranking_members", size: "full", config: { period: 30, limit: 10 } },
      { id: "vg-evolucao", type: "timeline", size: "lg", config: { period: 30 } },
      { id: "vg-whatsapp", type: "kpi_messageable", size: "sm", config: {} },
      { id: "vg-bairros", type: "by_neighborhood", size: "md", config: { limit: 10 } },
      { id: "vg-apoio", type: "by_support", size: "md", config: {} },
      { id: "vg-recentes", type: "recent_voters", size: "full", config: { limit: 8 } },
    ],
  },
  equipe: {
    key: "equipe",
    name: "Desempenho da equipe",
    description: "Ranking semanal dos cabos eleitorais, coordenadores e metas individuais.",
    widgets: [
      { id: "eq-equipe", type: "kpi_team", size: "sm", config: { period: 7 } },
      { id: "eq-hoje", type: "kpi_today", size: "sm", config: {} },
      { id: "eq-semana", type: "kpi_period", size: "sm", config: { period: 7 } },
      { id: "eq-meta", type: "kpi_goal", size: "sm", config: {} },
      { id: "eq-ranking", type: "ranking_members", size: "full", config: { period: 7, limit: 20 } },
      { id: "eq-coord", type: "ranking_coordinators", size: "full", config: { period: 30, limit: 10 } },
      { id: "eq-metas", type: "goals_progress", size: "md", config: { limit: 10 } },
      { id: "eq-evolucao", type: "timeline", size: "md", config: { period: 30 } },
    ],
  },
  territorial: {
    key: "territorial",
    name: "Territorial",
    description: "Onde estão os eleitores: bairros, cidades e perfil da base.",
    widgets: [
      { id: "te-total", type: "kpi_total", size: "sm", config: {} },
      { id: "te-periodo", type: "kpi_period", size: "sm", config: { period: 30 } },
      { id: "te-whatsapp", type: "kpi_messageable", size: "sm", config: {} },
      { id: "te-meta", type: "kpi_goal", size: "sm", config: {} },
      { id: "te-bairros", type: "by_neighborhood", size: "md", config: { limit: 15 } },
      { id: "te-cidades", type: "by_city", size: "md", config: { limit: 10 } },
      { id: "te-idade", type: "by_age", size: "md", config: {} },
      { id: "te-genero", type: "by_gender", size: "md", config: {} },
    ],
  },
  comunicacao: {
    key: "comunicacao",
    name: "Comunicação (WhatsApp)",
    description: "Base apta a receber mensagens e resultados dos disparos.",
    widgets: [
      { id: "co-whatsapp", type: "kpi_messageable", size: "sm", config: {} },
      { id: "co-total", type: "kpi_total", size: "sm", config: {} },
      { id: "co-periodo", type: "kpi_period", size: "sm", config: { period: 30 } },
      { id: "co-hoje", type: "kpi_today", size: "sm", config: {} },
      { id: "co-disparos", type: "broadcasts", size: "full", config: { period: 30 } },
      { id: "co-apoio", type: "by_support", size: "md", config: {} },
      { id: "co-origem", type: "by_source", size: "md", config: {} },
    ],
  },
};

export function isDashboardPresetKey(value: unknown): value is DashboardPresetKey {
  return typeof value === "string" && (DASHBOARD_PRESET_KEYS as readonly string[]).includes(value);
}

/** Cópia profunda dos widgets de um modelo (evita compartilhar referências do objeto constante) */
export function presetWidgets(key: DashboardPresetKey): DashboardWidget[] {
  return structuredClone(DASHBOARD_PRESETS[key].widgets);
}

/** Cria os dashboards-modelo padrão de uma campanha recém-criada (dentro da transação recebida) */
export async function createDefaultDashboards(tx: Prisma.TransactionClient, campaignId: string): Promise<void> {
  for (const key of DASHBOARD_PRESET_KEYS) {
    const preset = DASHBOARD_PRESETS[key];
    await tx.dashboard.create({
      data: {
        campaignId,
        ownerId: null,
        name: preset.name,
        description: preset.description,
        shared: true,
        isDefault: key === "visao_geral",
        widgets: presetWidgets(key) as unknown as Prisma.InputJsonValue,
      },
    });
  }
}
