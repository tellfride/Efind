// Trilha de auditoria. Nunca lança erro (auditoria não pode derrubar a operação principal).
import { headers } from "next/headers";
import { prisma } from "./db";
import { getClientIp } from "./utils";

/** Ações auditadas conhecidas (strings livres também são aceitas, mantenha o padrão "entidade.verbo") */
export const AUDIT_ACTIONS = {
  "auth.login": "Login",
  "auth.login_failed": "Tentativa de login falhou",
  "auth.logout": "Logout",
  "auth.password_change": "Troca de senha",
  "campaign.create": "Campanha criada",
  "campaign.update": "Campanha atualizada",
  "campaign.suspend": "Campanha suspensa",
  "campaign.activate": "Campanha reativada",
  "user.create": "Usuário criado",
  "user.update": "Usuário atualizado",
  "user.deactivate": "Usuário desativado",
  "user.activate": "Usuário reativado",
  "user.delete": "Usuário excluído",
  "user.password_reset": "Senha redefinida",
  "permissions.update": "Permissões alteradas",
  "voter.create": "Eleitor cadastrado",
  "voter.public_register": "Eleitor se cadastrou pelo link",
  "voter.update": "Eleitor atualizado",
  "voter.delete": "Eleitor excluído",
  "voter.export": "Eleitores exportados",
  "voter.import": "Eleitores importados",
  "voter.opt_out": "Eleitor descadastrado do WhatsApp",
  "template.create": "Modelo criado",
  "template.update": "Modelo atualizado",
  "template.delete": "Modelo excluído",
  "broadcast.create": "Disparo criado",
  "broadcast.start": "Disparo iniciado",
  "broadcast.pause": "Disparo pausado",
  "broadcast.resume": "Disparo retomado",
  "broadcast.cancel": "Disparo cancelado",
  "broadcast.delete": "Disparo excluído",
  "whatsapp.connection_create": "Conexão de WhatsApp criada",
  "whatsapp.connection_update": "Conexão de WhatsApp atualizada",
  "whatsapp.connection_delete": "Conexão de WhatsApp excluída",
  "whatsapp.connection_test": "Conexão de WhatsApp testada",
  "dashboard.create": "Dashboard criado",
  "dashboard.update": "Dashboard atualizado",
  "dashboard.delete": "Dashboard excluído",
  "settings.update": "Configurações atualizadas",
} as const;

export interface AuditInput {
  action: keyof typeof AUDIT_ACTIONS | (string & {});
  campaignId?: string | null;
  userId?: string | null;
  entity?: string;
  entityId?: string;
  details?: Record<string, unknown>;
  /** Se omitido, tenta ler do request atual */
  ip?: string;
}

export async function audit(input: AuditInput): Promise<void> {
  try {
    let ip = input.ip;
    if (!ip) {
      try {
        ip = getClientIp(await headers());
      } catch {
        ip = undefined; // fora de um request (worker/scripts)
      }
    }
    await prisma.auditLog.create({
      data: {
        action: input.action,
        campaignId: input.campaignId ?? null,
        userId: input.userId ?? null,
        entity: input.entity,
        entityId: input.entityId,
        details: (input.details ?? undefined) as never,
        ip,
      },
    });
  } catch (err) {
    console.error("[audit] falha ao registrar", input.action, err);
  }
}
