"""Lógica pura da matriz de permissões: normalização, diff, exceções em três estados e serialização."""

from django.test import SimpleTestCase

from apps.core.constants import Role
from apps.core.permissions import ACTIONS, MODULE_KEYS, MODULES, can, default_permissions_for, resolve_permissions
from apps.team import permission_logic as pl


def row(module, **values):
    base = {"module": module, **{f"can_{a}": None for a in ACTIONS}}
    return {**base, **values}


class RoleMatrixTests(SimpleTestCase):
    def test_normalize_drops_unknown_and_unsupported(self):
        raw = {
            "mapa": {"view": True, "delete": True, "export": True},  # mapa só suporta "view"
            "inexistente": {"view": True},
            "eleitores": {"view": True, "create": True, "export": "on"},  # só True literal vale
        }
        m = pl.normalize_matrix(raw)
        self.assertEqual(set(m), set(MODULE_KEYS))
        self.assertEqual(m["mapa"], {"view": True, "create": False, "edit": False, "delete": False, "export": False})
        self.assertTrue(m["eleitores"]["create"])
        self.assertFalse(m["eleitores"]["export"])
        self.assertNotIn("inexistente", m)

    def test_without_view_row_is_cleared(self):
        m = pl.normalize_matrix({"eleitores": {"view": False, "create": True, "edit": True, "delete": True, "export": True}})
        self.assertFalse(any(m["eleitores"].values()))

    def test_garbage_input(self):
        for raw in (None, [], "x", 3, {"eleitores": "oi"}):
            m = pl.normalize_matrix(raw)
            self.assertFalse(any(any(r.values()) for r in m.values()))

    def test_defaults_match_core_defaults(self):
        for role in (Role.COORDENADOR, Role.CABO):
            self.assertEqual(pl.default_matrix(role), pl.normalize_matrix(default_permissions_for(role)))
        self.assertTrue(pl.default_matrix(Role.COORDENADOR)["equipe"]["create"])
        self.assertFalse(pl.default_matrix(Role.CABO)["equipe"]["view"])

    def test_matrix_from_rows_overlays_defaults(self):
        m = pl.matrix_from_rows(Role.CABO, [row("eleitores", can_view=True, can_export=True), row("mapa", can_view=False)])
        self.assertTrue(m["eleitores"]["export"])
        self.assertFalse(m["mapa"]["view"])
        self.assertTrue(m["dashboard"]["view"])  # padrão preservado

    def test_matrix_to_rows_roundtrip(self):
        m = pl.default_matrix(Role.COORDENADOR)
        rows = pl.matrix_to_rows(m)
        self.assertEqual([r["module"] for r in rows], list(MODULE_KEYS))
        for r in rows:
            self.assertEqual(set(r) - {"module"}, {f"can_{a}" for a in ACTIONS})
            self.assertTrue(all(isinstance(v, bool) for k, v in r.items() if k != "module"))
        self.assertEqual(pl.matrix_from_rows(Role.COORDENADOR, rows), m)

    def test_parse_post_and_normalize(self):
        post = {
            "perm__eleitores__view": "on",
            "perm__eleitores__create": "on",
            "perm__eleitores__export": "on",
            "perm__mapa__delete": "on",  # não suportado: ignorado
            "perm__equipe__edit": "on",  # sem "view" → linha limpa
            "perm__falso__view": "on",
        }
        m = pl.normalize_matrix(pl.parse_matrix_post(post))
        self.assertTrue(m["eleitores"]["view"] and m["eleitores"]["create"] and m["eleitores"]["export"])
        self.assertFalse(m["eleitores"]["edit"])
        self.assertFalse(m["mapa"]["delete"])
        self.assertFalse(any(m["equipe"].values()))

    def test_diff(self):
        before = pl.default_matrix(Role.CABO)
        after = pl.normalize_matrix(before)
        after["eleitores"]["export"] = True
        after["mapa"] = {a: False for a in ACTIONS}
        changes = pl.diff_matrices(before, after)
        pairs = {(c.module, c.action, c.after) for c in changes}
        self.assertEqual(pairs, {("eleitores", "export", True), ("mapa", "view", False)})
        self.assertEqual(pl.diff_matrices(before, before), [])

    def test_describe_change_has_only_names(self):
        text = pl.describe_change(pl.PermissionChange("eleitores", "export", False, True))
        self.assertEqual(text, "Eleitores · Exportar: não → sim")
        self.assertEqual(pl.describe_change(pl.PermissionChange("mapa", "view", None, False)), "Mapa · Ver: herdar → não")

    def test_module_actions_in_column_order(self):
        self.assertEqual(pl.module_actions("whatsapp"), ("view", "edit"))
        self.assertEqual(pl.module_actions("eleitores"), ACTIONS)


class OverrideTests(SimpleTestCase):
    def test_tri_state_conversion(self):
        self.assertIs(pl.to_tri_state(True), True)
        self.assertIs(pl.to_tri_state("allow"), True)
        self.assertIs(pl.to_tri_state(False), False)
        self.assertIs(pl.to_tri_state("deny"), False)
        for v in (None, "inherit", "", "xyz", 1, 0):
            self.assertIsNone(pl.to_tri_state(v))
        self.assertEqual(pl.tri_to_value(None), "inherit")
        self.assertEqual(pl.tri_to_value(True), "allow")
        self.assertEqual(pl.tri_to_value(False), "deny")

    def test_deny_view_clears_other_actions(self):
        ov = pl.normalize_overrides({"eleitores": {"view": "deny", "create": "allow", "export": "allow"}})
        self.assertIs(ov["eleitores"]["view"], False)
        self.assertIsNone(ov["eleitores"]["create"])
        self.assertIsNone(ov["eleitores"]["export"])

    def test_allow_action_enables_view_when_role_has_none(self):
        inherited = pl.default_matrix(Role.CABO)  # cabo não vê "equipe"
        ov = pl.normalize_overrides({"equipe": {"create": "allow"}}, inherited)
        self.assertIs(ov["equipe"]["view"], True)
        self.assertIs(ov["equipe"]["create"], True)
        # quando o papel já vê o módulo, "Ver" continua herdando
        ov2 = pl.normalize_overrides({"eleitores": {"export": "allow"}}, inherited)
        self.assertIsNone(ov2["eleitores"]["view"])

    def test_unsupported_actions_are_dropped(self):
        ov = pl.normalize_overrides({"mapa": {"view": "allow", "delete": "allow", "export": "deny"}})
        self.assertIs(ov["mapa"]["view"], True)
        self.assertIsNone(ov["mapa"]["delete"])
        self.assertIsNone(ov["mapa"]["export"])

    def test_serialize_upserts_and_deletes(self):
        ov = pl.normalize_overrides({"eleitores": {"export": "allow"}, "mapa": {"view": "deny"}})
        upserts, deletes = pl.serialize_overrides(ov)
        modules = {u["module"] for u in upserts}
        self.assertEqual(modules, {"eleitores", "mapa"})
        self.assertEqual(set(deletes), set(MODULE_KEYS) - modules)
        eleitores = next(u for u in upserts if u["module"] == "eleitores")
        self.assertIs(eleitores["can_export"], True)
        self.assertIsNone(eleitores["can_view"])
        # tudo herdado → nada a gravar, tudo a apagar
        upserts, deletes = pl.serialize_overrides(pl.empty_overrides())
        self.assertEqual((upserts, set(deletes)), ([], set(MODULE_KEYS)))

    def test_rows_roundtrip(self):
        ov = pl.normalize_overrides({"eleitores": {"export": "allow", "delete": "deny"}, "dashboard": {"view": "deny"}})
        upserts, _ = pl.serialize_overrides(ov)
        self.assertEqual(pl.overrides_from_rows(upserts), ov)
        self.assertEqual(pl.count_overrides(ov), 3)
        self.assertEqual(pl.count_overrides(pl.empty_overrides()), 0)

    def test_parse_post(self):
        raw = pl.parse_overrides_post({"ov__eleitores__export": "allow", "ov__eleitores__create": "deny", "ov__mapa__delete": "allow"})
        self.assertEqual(raw["eleitores"]["export"], "allow")
        self.assertEqual(raw["eleitores"]["edit"], "inherit")
        self.assertNotIn("delete", raw["mapa"])  # coluna não suportada nem é lida

    def test_diff_overrides(self):
        before = pl.empty_overrides()
        after = pl.normalize_overrides({"eleitores": {"export": "allow"}})
        changes = pl.diff_overrides(before, after)
        self.assertEqual([(c.module, c.action, c.before, c.after) for c in changes], [("eleitores", "export", None, True)])
        self.assertEqual(pl.diff_overrides(after, after), [])

    def test_effective_permissions_matches_core_resolution(self):
        inherited = pl.default_matrix(Role.CABO)
        ov = pl.normalize_overrides({"eleitores": {"export": "allow", "create": "deny"}, "dashboard": {"view": "deny"}}, inherited)
        eff = pl.effective_permissions(Role.CABO, inherited, ov)
        self.assertTrue(can(eff, "eleitores", "export"))
        self.assertFalse(can(eff, "eleitores", "create"))
        self.assertTrue(can(eff, "eleitores", "edit"))
        self.assertFalse(can(eff, "dashboard", "view"))
        upserts, _ = pl.serialize_overrides(ov)
        self.assertEqual(eff, resolve_permissions(Role.CABO, pl.matrix_to_rows(inherited), upserts))

    def test_module_catalog_is_consistent(self):
        for key in MODULE_KEYS:
            self.assertIn("view", MODULES[key]["actions"])
