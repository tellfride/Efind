// Matriz de permissões por módulo. Este arquivo é puro (sem acesso ao banco) para ser usado
// tanto no servidor quanto em componentes cliente.
import type { Role, ConfigurableRole } from "./constants";

export const ACTIONS = ["view", "create", "edit", "delete", "export"] as const;
export type Action = (typeof ACTIONS)[number];

export const ACTION_LABELS: Record<Action, string> = {
  view: "Ver",
  create: "Criar",
  edit: "Editar",
  delete: "Excluir",
  export: "Exportar",
};

export const MODULES = {
  dashboard: {
    label: "Dashboards",
    description: "Painéis com indicadores. Criar/editar = montar dashboards próprios.",
    actions: ["view", "create", "edit", "delete"],
  },
  eleitores: {
    label: "Eleitores",
    description: "Cadastro e lista de eleitores (cada usuário vê apenas sua rede).",
    actions: ["view", "create", "edit", "delete", "export"],
  },
  mapa: {
    label: "Mapa",
    description: "Mapa por bairro/CEP dos eleitores da rede do usuário.",
    actions: ["view"],
  },
  meu_link: {
    label: "Meu link / QR Code",
    description: "Link e QR Code pessoal para cadastro de eleitores.",
    actions: ["view"],
  },
  equipe: {
    label: "Equipe",
    description: "Coordenadores e cabos eleitorais. Coordenador gerencia apenas seus cabos.",
    actions: ["view", "create", "edit", "delete"],
  },
  modelos: {
    label: "Modelos de mensagem",
    description: "Textos com variáveis usados nos disparos.",
    actions: ["view", "create", "edit", "delete"],
  },
  disparos: {
    label: "Disparos de WhatsApp",
    description: "Envio em massa para eleitores que consentiram. Editar = pausar/retomar/cancelar.",
    actions: ["view", "create", "edit", "delete"],
  },
  whatsapp: {
    label: "API do WhatsApp",
    description: "Conexões e credenciais dos provedores de WhatsApp.",
    actions: ["view", "edit"],
  },
  configuracoes: {
    label: "Configurações da campanha",
    description: "Identidade visual, formulário público e textos de consentimento.",
    actions: ["view", "edit"],
  },
  auditoria: {
    label: "Auditoria",
    description: "Registro de acessos, alterações e exportações (LGPD).",
    actions: ["view"],
  },
} as const satisfies Record<string, { label: string; description: string; actions: readonly Action[] }>;

export type ModuleKey = keyof typeof MODULES;
export const MODULE_KEYS = Object.keys(MODULES) as ModuleKey[];

export type ModulePermission = Record<Action, boolean>;
export type PermissionSet = Record<ModuleKey, ModulePermission>;

/** Forma das linhas RolePermission/UserPermission relevantes para a resolução */
export interface PermissionRow {
  module: string;
  canView: boolean | null;
  canCreate: boolean | null;
  canEdit: boolean | null;
  canDelete: boolean | null;
  canExport: boolean | null;
}

const COLUMN_BY_ACTION: Record<Action, keyof Omit<PermissionRow, "module">> = {
  view: "canView",
  create: "canCreate",
  edit: "canEdit",
  delete: "canDelete",
  export: "canExport",
};
export function actionColumn(action: Action) {
  return COLUMN_BY_ACTION[action];
}

export function moduleSupports(module: ModuleKey, action: Action): boolean {
  return (MODULES[module].actions as readonly Action[]).includes(action);
}

function emptyModule(): ModulePermission {
  return { view: false, create: false, edit: false, delete: false, export: false };
}

function fromActions(module: ModuleKey, actions: readonly Action[]): ModulePermission {
  const p = emptyModule();
  for (const a of actions) if (moduleSupports(module, a)) p[a] = true;
  return p;
}

/** Permissões padrão de cada papel configurável (aplicadas ao criar a campanha e quando não há linha no banco) */
export const DEFAULT_ROLE_PERMISSIONS: Record<ConfigurableRole, Partial<Record<ModuleKey, readonly Action[]>>> = {
  COORDENADOR: {
    dashboard: ["view", "create", "edit", "delete"],
    eleitores: ["view", "create", "edit", "export"],
    mapa: ["view"],
    meu_link: ["view"],
    equipe: ["view", "create", "edit"],
    modelos: ["view"],
    disparos: ["view"],
  },
  CABO: {
    dashboard: ["view"],
    eleitores: ["view", "create", "edit"],
    mapa: ["view"],
    meu_link: ["view"],
  },
};

export function defaultPermissionsFor(role: ConfigurableRole): PermissionSet {
  const set = {} as PermissionSet;
  for (const m of MODULE_KEYS) set[m] = fromActions(m, DEFAULT_ROLE_PERMISSIONS[role][m] ?? []);
  return set;
}

export function fullPermissions(): PermissionSet {
  const set = {} as PermissionSet;
  for (const m of MODULE_KEYS) set[m] = fromActions(m, MODULES[m].actions);
  return set;
}

export function noPermissions(): PermissionSet {
  const set = {} as PermissionSet;
  for (const m of MODULE_KEYS) set[m] = emptyModule();
  return set;
}

/**
 * Calcula as permissões efetivas:
 *  - ADMIN: tudo; SUPER_ADMIN: nada dentro de campanhas (usa /super).
 *  - COORDENADOR/CABO: padrão do papel → linhas RolePermission da campanha → exceções UserPermission.
 *  - Ações não suportadas pelo módulo ficam sempre false; sem "view" nenhuma outra ação vale.
 */
export function resolvePermissions(
  role: Role,
  rolePermissions: PermissionRow[] = [],
  userOverrides: PermissionRow[] = [],
): PermissionSet {
  if (role === "ADMIN") return fullPermissions();
  if (role === "SUPER_ADMIN") return noPermissions();

  const set = defaultPermissionsFor(role);
  const apply = (rows: PermissionRow[]) => {
    for (const row of rows) {
      if (!(row.module in MODULES)) continue;
      const m = row.module as ModuleKey;
      for (const a of MODULES[m].actions as readonly Action[]) {
        const v = row[COLUMN_BY_ACTION[a]];
        if (v !== null && v !== undefined) set[m][a] = v;
      }
    }
  };
  apply(rolePermissions);
  apply(userOverrides);

  for (const m of MODULE_KEYS) {
    if (!set[m].view) set[m] = emptyModule();
  }
  return set;
}

export function can(perms: PermissionSet | undefined | null, module: ModuleKey, action: Action = "view"): boolean {
  return !!perms?.[module]?.[action];
}
