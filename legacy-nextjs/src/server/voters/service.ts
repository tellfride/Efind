// Operações de banco do módulo de eleitores (usadas pelas Server Actions e páginas do painel).
// O escopo de acesso já deve ter sido verificado por quem chama (authorize + findVoterInScope).
import { after } from "next/server";
import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import { canAccessTeamMember, teamScopeWhere } from "@/server/access";
import { geocodeVoter } from "@/server/geo/geocode";
import type { ImportedVoter } from "@/components/voters/csv-import";
import { startOfDaySaoPaulo } from "@/components/voters/voter-utils";

/** Geocodifica depois de responder ao usuário. Se falhar, o eleitor fica PENDING e o worker tenta de novo. */
export function scheduleGeocode(voterId: string): void {
  after(async () => {
    try {
      await geocodeVoter(voterId);
    } catch {
      // mantém geoStatus PENDING para o worker
    }
  });
}

export function isUniqueViolation(err: unknown): boolean {
  return err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002";
}

export interface RegistrarOption {
  id: string;
  name: string;
  role: string;
}

/** Quem pode constar como "cadastrado por": membros ativos no escopo (CABO não escolhe — é sempre ele) */
export async function getRegistrarOptions(user: CampaignUser): Promise<RegistrarOption[]> {
  if (user.role === "CABO") return [];
  return prisma.user.findMany({
    where: { AND: [teamScopeWhere(user), { active: true }] },
    select: { id: true, name: true, role: true },
    orderBy: { name: "asc" },
  });
}

/** Valida o "cadastrado por" vindo do cliente: mesmo campanha + escopo + ativo. Vazio = o próprio usuário. */
export async function resolveRegistrar(
  user: CampaignUser,
  requestedId: string | null | undefined,
): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  if (!requestedId || requestedId === user.id || user.role === "CABO") return { ok: true, id: user.id };
  if (!(await canAccessTeamMember(user, requestedId))) {
    return { ok: false, error: "Selecione um membro da sua equipe." };
  }
  const target = await prisma.user.findFirst({
    where: { id: requestedId, campaignId: user.campaignId, active: true },
    select: { id: true },
  });
  return target ? { ok: true, id: target.id } : { ok: false, error: "Este membro da equipe está desativado." };
}

/** Mensagens ainda na fila deste eleitor deixam de ser enviadas (descadastro ou exclusão) */
function skipQueuedMessages(campaignId: string, voterId: string, reason: string) {
  return prisma.broadcastMessage.updateMany({
    where: { campaignId, voterId, status: "PENDING" },
    data: { status: "SKIPPED", error: reason },
  });
}

/** Descadastro do WhatsApp feito pelo painel */
export async function optOutVoter(campaignId: string, voterId: string, now = new Date()): Promise<void> {
  await prisma.$transaction([
    prisma.voter.update({ where: { id: voterId }, data: { optOutAt: now, whatsappOptIn: false } }),
    skipQueuedMessages(campaignId, voterId, "Eleitor descadastrado do WhatsApp"),
  ]);
}

/**
 * Exclusão definitiva (direito do titular — LGPD art. 18, VI): remove o eleitor, as mensagens recebidas dele
 * e apaga telefone/texto das mensagens de disparos já registradas (os totais dos disparos são mantidos).
 */
export async function eraseVoter(campaignId: string, voterId: string): Promise<void> {
  await prisma.$transaction([
    skipQueuedMessages(campaignId, voterId, "Eleitor excluído"),
    prisma.broadcastMessage.updateMany({ where: { campaignId, voterId }, data: { phone: "", renderedBody: "" } }),
    prisma.inboundMessage.deleteMany({ where: { campaignId, voterId } }),
    prisma.voter.delete({ where: { id: voterId } }),
  ]);
}

// ---------- Meu link ----------

export interface MyLinkStats {
  today: number;
  last7Days: number;
  total: number;
  viaQr: number;
  viaLink: number;
  goal: number | null;
}

export async function getMyLinkStats(user: CampaignUser, now = new Date()): Promise<MyLinkStats> {
  const base = { campaignId: user.campaignId, registeredById: user.id };
  const [today, last7Days, total, viaQr, viaLink, me] = await Promise.all([
    prisma.voter.count({ where: { ...base, createdAt: { gte: startOfDaySaoPaulo(now) } } }),
    prisma.voter.count({ where: { ...base, createdAt: { gte: startOfDaySaoPaulo(now, 6) } } }),
    prisma.voter.count({ where: base }),
    prisma.voter.count({ where: { ...base, source: "QRCODE" } }),
    prisma.voter.count({ where: { ...base, source: "LINK" } }),
    prisma.user.findUnique({ where: { id: user.id }, select: { goal: true } }),
  ]);
  return { today, last7Days, total, viaQr, viaLink, goal: me?.goal ?? null };
}

export async function getMyRecentRegistrations(user: CampaignUser, take = 5) {
  return prisma.voter.findMany({
    where: { campaignId: user.campaignId, registeredById: user.id },
    orderBy: { createdAt: "desc" },
    take,
    select: { id: true, name: true, neighborhood: true, city: true, createdAt: true, source: true },
  });
}

// ---------- Importação ----------

export interface ImportExecution {
  imported: number;
  /** Linhas ignoradas porque o telefone já existe na campanha ou se repete no arquivo */
  duplicateRows: number[];
}

const CHUNK = 500;

/** Grava eleitores importados ignorando telefones já cadastrados (na campanha ou repetidos no arquivo) */
export async function importVoters(params: {
  campaignId: string;
  registeredById: string;
  whatsappOptIn: boolean;
  consentText: string;
  consentIp: string;
  records: { row: number; voter: ImportedVoter }[];
  now?: Date;
}): Promise<ImportExecution> {
  const now = params.now ?? new Date();
  const duplicateRows: number[] = [];

  // Repetidos no próprio arquivo: vale a primeira ocorrência
  const seen = new Set<string>();
  const unique: { row: number; voter: ImportedVoter }[] = [];
  for (const r of params.records) {
    if (seen.has(r.voter.phone)) duplicateRows.push(r.row);
    else {
      seen.add(r.voter.phone);
      unique.push(r);
    }
  }

  // Já cadastrados na campanha
  const existing = new Set<string>();
  const phones = unique.map((r) => r.voter.phone);
  for (let i = 0; i < phones.length; i += CHUNK) {
    const rows = await prisma.voter.findMany({
      where: { campaignId: params.campaignId, phone: { in: phones.slice(i, i + CHUNK) } },
      select: { phone: true },
    });
    rows.forEach((r) => existing.add(r.phone));
  }
  const toCreate = unique.filter((r) => {
    if (existing.has(r.voter.phone)) {
      duplicateRows.push(r.row);
      return false;
    }
    return true;
  });

  const toData = (v: ImportedVoter): Prisma.VoterCreateManyInput => ({
    campaignId: params.campaignId,
    registeredById: params.registeredById,
    name: v.name,
    phone: v.phone,
    email: v.email,
    birthDate: v.birthDate,
    gender: v.gender,
    cep: v.cep,
    street: v.street,
    number: v.number,
    complement: v.complement,
    neighborhood: v.neighborhood,
    city: v.city,
    state: v.state,
    electoralZone: v.electoralZone,
    electoralSection: v.electoralSection,
    supportLevel: v.supportLevel,
    tags: v.tags,
    source: "IMPORT",
    consentAt: now,
    consentIp: params.consentIp,
    consentText: params.consentText,
    whatsappOptIn: params.whatsappOptIn,
    geoStatus: "PENDING",
  });

  let imported = 0;
  for (let i = 0; i < toCreate.length; i += CHUNK) {
    const chunk = toCreate.slice(i, i + CHUNK);
    try {
      // Transação: o lote é gravado inteiro ou nada (o banco pode dividir o INSERT em vários comandos)
      const [res] = await prisma.$transaction([prisma.voter.createMany({ data: chunk.map((r) => toData(r.voter)) })]);
      imported += res.count;
    } catch (err) {
      if (!isUniqueViolation(err)) throw err;
      // Alguém cadastrou o mesmo telefone durante a importação: grava um a um
      for (const r of chunk) {
        try {
          await prisma.voter.create({ data: toData(r.voter) });
          imported++;
        } catch (e) {
          if (!isUniqueViolation(e)) throw e;
          duplicateRows.push(r.row);
        }
      }
    }
  }
  duplicateRows.sort((a, b) => a - b);
  return { imported, duplicateRows };
}
