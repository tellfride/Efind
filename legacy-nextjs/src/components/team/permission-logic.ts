// Lógica pura da matriz de permissões (usada no cliente e revalidada no servidor).
//  - Matriz do papel: boolean por módulo/ação. Desligar "Ver" limpa a linha; ligar qualquer ação liga "Ver".
//  - Exceções por usuário: três estados (null = herda do papel, true = permitir, false = negar).
import {
  ACTION_LABELS,
  MODULES,
  MODULE_KEYS,
  actionColumn,
  defaultPermissionsFor,
  moduleSupports,
  resolvePermissions,
  type Action,
  type ModuleKey,
  type ModulePermission,
  type PermissionRow,
  type PermissionSet,
} from "@/lib/permissions";
import type { ConfigurableRole } from "@/lib/constants";

export type TriState = boolean | null;
export type OverrideRowValues = Record<Action, TriState>;
export type OverrideMatrix = Record<ModuleKey, OverrideRowValues>;

/** Ações suportadas por um módulo, na ordem das colunas */
export function moduleActions(module: ModuleKey): Action[] {
  return [...(MODULES[module].actions as readonly Action[])];
}

function emptyModule(): ModulePermission {
  return { view: false, create: false, edit: false, delete: false, export: false };
}

function emptyOverrideRow(): OverrideRowValues {
  return { view: null, create: null, edit: null, delete: null, export: null };
}

function cloneMatrix(matrix: PermissionSet): PermissionSet {
  const out = {} as PermissionSet;
  for (const m of MODULE_KEYS) out[m] = { ...emptyModule(), ...matrix[m] };
  return out;
}

// ---------------------------------------------------------------------------
// Matriz do papel
// ---------------------------------------------------------------------------

/**
 * Normaliza uma matriz vinda do cliente: ignora módulos desconhecidos, ações não suportadas ficam false,
 * só aceita `true` literal e linhas sem "Ver" ficam vazias.
 */
export function normalizeMatrix(input: unknown): PermissionSet {
  const source = input && typeof input === "object" ? (input as Record<string, unknown>) : {};
  const out = {} as PermissionSet;
  for (const m of MODULE_KEYS) {
    const row = source[m] && typeof source[m] === "object" ? (source[m] as Record<string, unknown>) : {};
    const p = emptyModule();
    for (const a of moduleActions(m)) p[a] = row[a] === true;
    out[m] = p.view ? p : emptyModule();
  }
  return out;
}

/** Liga/desliga uma célula aplicando as regras de dependência do "Ver" */
export function toggleMatrixCell(matrix: PermissionSet, module: ModuleKey, action: Action, value: boolean): PermissionSet {
  if (!moduleSupports(module, action)) return matrix;
  const next = cloneMatrix(matrix);
  if (action === "view" && !value) {
    next[module] = emptyModule();
  } else {
    next[module] = { ...next[module], [action]: value };
    if (value) next[module].view = true;
  }
  return next;
}

/** Liga (todas as ações suportadas) ou desliga a linha inteira de um módulo */
export function setModuleRow(matrix: PermissionSet, module: ModuleKey, value: boolean): PermissionSet {
  const next = cloneMatrix(matrix);
  const p = emptyModule();
  if (value) for (const a of moduleActions(module)) p[a] = true;
  next[module] = p;
  return next;
}

/** Matriz padrão do papel (DEFAULT_ROLE_PERMISSIONS) */
export function defaultMatrix(role: ConfigurableRole): PermissionSet {
  return normalizeMatrix(defaultPermissionsFor(role));
}

/** Matriz atual do papel: linhas RolePermission sobre o padrão (mesma regra do login) */
export function roleMatrixFromRows(role: ConfigurableRole, rows: PermissionRow[]): PermissionSet {
  return normalizeMatrix(resolvePermissions(role, rows));
}

/** Linhas completas (todas as colunas booleanas) para gravar em RolePermission */
export function matrixToRows(matrix: PermissionSet): (PermissionRow & { module: ModuleKey })[] {
  return MODULE_KEYS.map((m) => {
    const row = { module: m, canView: false, canCreate: false, canEdit: false, canDelete: false, canExport: false };
    for (const a of moduleActions(m)) row[actionColumn(a)] = !!matrix[m]?.[a];
    return row;
  });
}

export interface PermissionChange {
  module: ModuleKey;
  action: Action;
  from: TriState;
  to: TriState;
}

/** Diferenças célula a célula entre duas matrizes de papel */
export function diffMatrices(before: PermissionSet, after: PermissionSet): PermissionChange[] {
  const changes: PermissionChange[] = [];
  for (const m of MODULE_KEYS) {
    for (const a of moduleActions(m)) {
      const from = !!before[m]?.[a];
      const to = !!after[m]?.[a];
      if (from !== to) changes.push({ module: m, action: a, from, to });
    }
  }
  return changes;
}

export function sameMatrix(a: PermissionSet, b: PermissionSet): boolean {
  return diffMatrices(a, b).length === 0;
}

function triLabel(v: TriState): string {
  if (v === null) return "herdar";
  return v ? "sim" : "não";
}

/** Texto curto de uma alteração para auditoria: "Eleitores · Exportar: não → sim" */
export function describeChange(change: PermissionChange): string {
  return `${MODULES[change.module].label} · ${ACTION_LABELS[change.action]}: ${triLabel(change.from)} → ${triLabel(change.to)}`;
}

// ---------------------------------------------------------------------------
// Exceções por usuário (três estados)
// ---------------------------------------------------------------------------

export function emptyOverrides(): OverrideMatrix {
  const out = {} as OverrideMatrix;
  for (const m of MODULE_KEYS) out[m] = emptyOverrideRow();
  return out;
}

function toTriState(v: unknown): TriState {
  return v === true ? true : v === false ? false : null;
}

/** Ajusta uma linha: ações não suportadas = null; negar "Ver" anula as demais (não teriam efeito) */
function normalizeOverrideRow(module: ModuleKey, row: Partial<Record<Action, unknown>>, inheritedView?: boolean): OverrideRowValues {
  const out = emptyOverrideRow();
  for (const a of moduleActions(module)) out[a] = toTriState(row[a]);
  if (out.view === false) {
    for (const a of moduleActions(module)) if (a !== "view") out[a] = null;
    return out;
  }
  // Permitir qualquer ação exige "Ver": se o papel não vê o módulo, a exceção passa a permitir "Ver"
  if (inheritedView === false && out.view === null && moduleActions(module).some((a) => a !== "view" && out[a] === true)) {
    out.view = true;
  }
  return out;
}

/**
 * Normaliza exceções vindas do cliente. `inherited` (matriz do papel) é opcional: quando informado,
 * permitir uma ação num módulo que o papel não vê também permite "Ver".
 */
export function normalizeOverrides(input: unknown, inherited?: PermissionSet): OverrideMatrix {
  const source = input && typeof input === "object" ? (input as Record<string, unknown>) : {};
  const out = emptyOverrides();
  for (const m of MODULE_KEYS) {
    const row = source[m] && typeof source[m] === "object" ? (source[m] as Record<string, unknown>) : {};
    out[m] = normalizeOverrideRow(m, row, inherited ? inherited[m].view : undefined);
  }
  return out;
}

/** Linhas UserPermission do banco → matriz de três estados */
export function overridesFromRows(rows: PermissionRow[]): OverrideMatrix {
  const out = emptyOverrides();
  for (const row of rows) {
    if (!(row.module in MODULES)) continue;
    const m = row.module as ModuleKey;
    const values: Partial<Record<Action, unknown>> = {};
    for (const a of moduleActions(m)) values[a] = row[actionColumn(a)];
    out[m] = normalizeOverrideRow(m, values);
  }
  return out;
}

/** Altera uma célula de exceção mantendo as regras de dependência do "Ver" */
export function setOverrideCell(
  overrides: OverrideMatrix,
  inherited: PermissionSet,
  module: ModuleKey,
  action: Action,
  value: TriState,
): OverrideMatrix {
  if (!moduleSupports(module, action)) return overrides;
  const row: OverrideRowValues = { ...emptyOverrideRow(), ...overrides[module], [action]: value };
  if (action === "view") {
    // Sem "Ver" efetivo (negado, ou herdado do papel que não vê) as demais exceções voltam a herdar
    const effectiveView = value === null ? inherited[module].view : value;
    if (!effectiveView) for (const a of moduleActions(module)) if (a !== "view") row[a] = null;
  }
  return { ...overrides, [module]: normalizeOverrideRow(module, row, inherited[module].view) };
}

export type OverrideDbRow = { module: ModuleKey; canView: TriState; canCreate: TriState; canEdit: TriState; canDelete: TriState; canExport: TriState };

/** Converte a matriz em linhas para gravar (upserts) e módulos sem nenhuma exceção (deletes) */
export function serializeOverrides(overrides: OverrideMatrix): { upserts: OverrideDbRow[]; deletes: ModuleKey[] } {
  const upserts: OverrideDbRow[] = [];
  const deletes: ModuleKey[] = [];
  for (const m of MODULE_KEYS) {
    const row = overrides[m] ?? emptyOverrideRow();
    const db: OverrideDbRow = { module: m, canView: null, canCreate: null, canEdit: null, canDelete: null, canExport: null };
    for (const a of moduleActions(m)) db[actionColumn(a)] = toTriState(row[a]);
    const hasAny = moduleActions(m).some((a) => db[actionColumn(a)] !== null);
    if (hasAny) upserts.push(db);
    else deletes.push(m);
  }
  return { upserts, deletes };
}

/** Quantidade de células com exceção (≠ herdar) */
export function countOverrides(overrides: OverrideMatrix): number {
  let n = 0;
  for (const m of MODULE_KEYS) for (const a of moduleActions(m)) if (overrides[m]?.[a] !== null && overrides[m]?.[a] !== undefined) n++;
  return n;
}

/** Diferenças entre duas matrizes de exceção (para auditoria e indicação de alterações não salvas) */
export function diffOverrides(before: OverrideMatrix, after: OverrideMatrix): PermissionChange[] {
  const changes: PermissionChange[] = [];
  for (const m of MODULE_KEYS) {
    for (const a of moduleActions(m)) {
      const from = toTriState(before[m]?.[a]);
      const to = toTriState(after[m]?.[a]);
      if (from !== to) changes.push({ module: m, action: a, from, to });
    }
  }
  return changes;
}

/** Permissões efetivas do usuário = matriz do papel + exceções (mesma regra de resolvePermissions) */
export function effectivePermissions(role: ConfigurableRole, inherited: PermissionSet, overrides: OverrideMatrix): PermissionSet {
  return resolvePermissions(role, matrixToRows(inherited), serializeOverrides(overrides).upserts);
}

/** Valor do <select> de três estados */
export type TriStateValue = "inherit" | "allow" | "deny";

export function triStateToValue(v: TriState): TriStateValue {
  return v === null ? "inherit" : v ? "allow" : "deny";
}

export function valueToTriState(v: string): TriState {
  return v === "allow" ? true : v === "deny" ? false : null;
}
