import { describe, expect, it } from "vitest";
import { can, defaultPermissionsFor, resolvePermissions, type PermissionRow } from "@/lib/permissions";
import { formatPhone, normalizeBrPhone } from "@/lib/phone";
import { extractVariables, renderTemplate } from "@/lib/template-vars";
import { parseVoterFilters, voterFiltersToSearchParams } from "@/lib/voter-filters";
import { parseTags, serializeTags, toCsv } from "@/lib/utils";
import { decryptJson, encryptJson } from "@/lib/crypto";

const row = (module: string, v: Partial<Omit<PermissionRow, "module">>): PermissionRow => ({
  module,
  canView: null,
  canCreate: null,
  canEdit: null,
  canDelete: null,
  canExport: null,
  ...v,
});

describe("permissões", () => {
  it("ADMIN tem tudo, SUPER_ADMIN nada dentro da campanha", () => {
    const admin = resolvePermissions("ADMIN");
    expect(can(admin, "whatsapp", "edit")).toBe(true);
    expect(can(admin, "mapa", "delete")).toBe(false); // ação não suportada pelo módulo
    expect(can(resolvePermissions("SUPER_ADMIN"), "eleitores", "view")).toBe(false);
  });

  it("aplica padrão → papel → exceção do usuário", () => {
    expect(can(defaultPermissionsFor("CABO"), "eleitores", "export")).toBe(false);
    const p = resolvePermissions("CABO", [row("eleitores", { canExport: true })], [row("eleitores", { canCreate: false })]);
    expect(can(p, "eleitores", "export")).toBe(true);
    expect(can(p, "eleitores", "create")).toBe(false);
    expect(can(p, "eleitores", "view")).toBe(true);
  });

  it("sem view, nenhuma outra ação vale", () => {
    const p = resolvePermissions("COORDENADOR", [row("eleitores", { canView: false })]);
    expect(can(p, "eleitores", "create")).toBe(false);
  });
});

describe("telefone", () => {
  it("normaliza formatos brasileiros", () => {
    expect(normalizeBrPhone("(11) 98765-4321")).toBe("5511987654321");
    expect(normalizeBrPhone("+55 19 3232-1234")).toBe("551932321234");
    expect(normalizeBrPhone("011987654321")).toBe("5511987654321");
    expect(normalizeBrPhone("(00) 98765-4321")).toBeNull();
    expect(normalizeBrPhone("(11) 88765-4321")).toBeNull(); // celular sem 9
    expect(normalizeBrPhone("123")).toBeNull();
    expect(formatPhone("5511987654321")).toBe("(11) 98765-4321");
  });
});

describe("modelos", () => {
  it("renderiza variáveis com espaços e caixa variada", () => {
    expect(renderTemplate("Oi {{ primeiro_nome }} do {{BAIRRO}} {{x}}", { primeiro_nome: "Ana", bairro: "Centro" })).toBe("Oi Ana do Centro ");
    expect(extractVariables("{{nome}} {{bairro}} {{nome}}")).toEqual(["nome", "bairro"]);
  });
});

describe("filtros de eleitores", () => {
  it("ida e volta pela URL, descartando inválidos", () => {
    const f = parseVoterFilters(new URLSearchParams("bairro=Centro&bairro=Cambuí&genero=F&genero=Z&idadeMin=18&whatsapp=1&de=2026-01-01&ate=errado"));
    expect(f).toEqual({ neighborhoods: ["Centro", "Cambuí"], ageMin: 18, messageable: true, createdFrom: "2026-01-01" });
    // genero=Z invalida o array inteiro (descartado)
    const sp = voterFiltersToSearchParams(f);
    expect(parseVoterFilters(sp)).toEqual(f);
  });
});

describe("utilitários", () => {
  it("tags normalizadas", () => {
    expect(serializeTags("Saúde, jovem ,saude")).toBe(",saude,jovem,");
    expect(parseTags(",saude,jovem,")).toEqual(["saude", "jovem"]);
  });
  it("CSV protege contra fórmulas", () => {
    const csv = toCsv([{ a: "=1+1", b: 'x"y' }], [{ key: "a", label: "A" }, { key: "b", label: "B" }]);
    expect(csv).toContain("'=1+1");
    expect(csv).toContain('"x""y"');
  });
  it("criptografia ida e volta", () => {
    process.env.ENCRYPTION_KEY = Buffer.alloc(32, 7).toString("base64");
    const enc = encryptJson({ token: "segredo" });
    expect(enc.startsWith("v1:")).toBe(true);
    expect(decryptJson(enc)).toEqual({ token: "segredo" });
  });
});
