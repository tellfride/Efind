"""Matriz de permissões (/painel/permissoes/): acesso exclusivo do ADMIN, gravação por papel, restaurar padrão,
exceções por usuário em três estados, auditoria, isolamento entre campanhas e efeito imediato."""

import json
import re
import uuid

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import RolePermission, UserPermission
from apps.accounts.services import permissions_for
from apps.auditlog.models import AuditLog
from apps.core.constants import Role
from apps.core.permissions import ACTIONS, MODULE_KEYS, can
from apps.team import permission_logic as pl

from .helpers import fast_hashers, login, make_campaign, make_user


def matrix_post(matrix):
    """Matriz → dados de POST (checkboxes marcados)."""
    return {f"perm__{m}__{a}": "on" for m, row in matrix.items() for a, v in row.items() if v and a in pl.module_actions(m)}


@fast_hashers
class PermissionsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.camp = make_campaign("alfa")
        cls.other = make_campaign("beta")
        cls.admin = make_user(cls.camp, "admin@a.com", Role.ADMIN, name="Admin Alfa")
        cls.coord = make_user(cls.camp, "coord@a.com", Role.COORDENADOR, parent=cls.admin, name="Coord Alfa")
        cls.cabo = make_user(cls.camp, "cabo@a.com", Role.CABO, parent=cls.coord, name="Cabo Alfa")
        cls.admin_b = make_user(cls.other, "admin@b.com", Role.ADMIN, name="Admin Beta")
        cls.cabo_b = make_user(cls.other, "cabo@b.com", Role.CABO, parent=cls.admin_b, name="Cabo Beta Secreto")

    def role_matrix(self, role, campaign=None):
        rows = [r.as_row() for r in RolePermission.objects.filter(campaign=campaign or self.camp, role=role)]
        return pl.matrix_from_rows(role, rows)

    def save_role(self, client, slug, matrix):
        return client.post(reverse("team:permissions_role_save", args=[slug]), matrix_post(matrix))

    def audits(self):
        return AuditLog.objects.filter(campaign=self.camp, action="permissions.update")


class PermissionsAccessTests(PermissionsBase):
    def all_urls(self):
        return {
            "get": [reverse("team:permissions")],
            "post": [
                reverse("team:permissions_role_save", args=["coordenador"]),
                reverse("team:permissions_role_save", args=["cabo"]),
                reverse("team:permissions_role_reset", args=["cabo"]),
                reverse("team:permissions_user_save", args=[self.cabo.pk]),
            ],
        }

    def test_anonymous_goes_to_login(self):
        urls = self.all_urls()
        for url in urls["get"]:
            r = Client().get(url)
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r["Location"].startswith("/login/"))
        for url in urls["post"]:
            r = Client().post(url, {})
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r["Location"].startswith("/login/"), url)

    def test_coordinator_and_cabo_are_forbidden_everywhere(self):
        before = list(RolePermission.objects.values_list("pk", "can_view", "can_export", "can_create"))
        urls = self.all_urls()
        for user in (self.coord, self.cabo):
            c = login(user)
            for url in urls["get"]:
                self.assertEqual(c.get(url).status_code, 403, (user.role, url))
            for url in urls["post"]:
                data = {"perm__equipe__view": "on", "perm__equipe__create": "on", "ov__eleitores__export": "allow"}
                self.assertEqual(c.post(url, data).status_code, 403, (user.role, url))
        self.assertEqual(before, list(RolePermission.objects.values_list("pk", "can_view", "can_export", "can_create")))
        self.assertFalse(UserPermission.objects.exists())
        self.assertFalse(self.audits().exists())

    def test_even_with_every_equipe_permission_the_matrix_stays_admin_only(self):
        RolePermission.objects.filter(campaign=self.camp, role=Role.COORDENADOR, module="equipe").update(
            can_view=True, can_create=True, can_edit=True, can_delete=True
        )
        c = login(self.coord)
        self.assertEqual(c.get(reverse("team:permissions")).status_code, 403)
        self.assertEqual(c.post(reverse("team:permissions_role_reset", args=["coordenador"])).status_code, 403)

    def test_csrf_is_enforced(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        r = c.post(reverse("team:permissions_role_save", args=["cabo"]), {"perm__equipe__view": "on"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.role_matrix(Role.CABO)["equipe"]["view"])

    def test_actions_reject_get(self):
        c = login(self.admin)
        for url in self.all_urls()["post"]:
            self.assertEqual(c.get(url).status_code, 405, url)

    def test_super_admin_is_redirected(self):
        from apps.accounts.models import User

        sup = User.objects.create_superuser("super@x.com", "Senha@12345")
        r = login(sup).get(reverse("team:permissions"))
        self.assertEqual((r.status_code, r["Location"]), (302, "/super/"))


class PermissionsPageTests(PermissionsBase):
    def test_page_lists_every_module_with_supported_cells(self):
        r = login(self.admin).get(reverse("team:permissions"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["slug"] for t in r.context["tabs"]], ["coordenador", "cabo"])
        self.assertEqual(r.context["active_tab"], "coordenador")
        for tab in r.context["tabs"]:
            self.assertEqual([row["key"] for row in tab["rows"]], list(MODULE_KEYS))
            mapa = next(row for row in tab["rows"] if row["key"] == "mapa")
            supported = [c["action"] for c in mapa["cells"] if c["supported"]]
            self.assertEqual(supported, ["view"])
            self.assertEqual([c["action"] for c in mapa["cells"]], list(ACTIONS))
        for text in ("Exceções por usuário", "Restaurar padrão", "Eleitores", "Disparos de WhatsApp", "administrador"):
            self.assertContains(r, text)
        # nenhum dado de outra campanha
        self.assertNotContains(r, "Cabo Beta Secreto")
        self.assertNotContains(r, "Admin Beta")
        # config para o Alpine é JSON válido
        m = re.search(r'<script id="perm-config" type="application/json">(.*?)</script>', r.content.decode(), re.S)
        cfg = json.loads(m.group(1))
        self.assertEqual(set(cfg["roles"]), {"coordenador", "cabo"})
        self.assertEqual(cfg["supported"]["mapa"], ["view"])

    def test_tab_parameter(self):
        c = login(self.admin)
        self.assertEqual(c.get(reverse("team:permissions"), {"aba": "cabo"}).context["active_tab"], "cabo")
        self.assertEqual(c.get(reverse("team:permissions"), {"aba": "admin"}).context["active_tab"], "coordenador")

    def test_current_values_come_from_database_rows(self):
        RolePermission.objects.filter(campaign=self.camp, role=Role.CABO, module="eleitores").update(can_export=True)
        r = login(self.admin).get(reverse("team:permissions"))
        cabo = next(t for t in r.context["tabs"] if t["slug"] == "cabo")
        eleitores = next(row for row in cabo["rows"] if row["key"] == "eleitores")
        export = next(c for c in eleitores["cells"] if c["action"] == "export")
        self.assertTrue(export["checked"])
        self.assertFalse(export["default"])
        self.assertFalse(cabo["is_default"])
        coord = next(t for t in r.context["tabs"] if t["slug"] == "coordenador")
        self.assertTrue(coord["is_default"])

    def test_falls_back_to_defaults_without_rows(self):
        RolePermission.objects.filter(campaign=self.camp).delete()
        r = login(self.admin).get(reverse("team:permissions"))
        self.assertTrue(all(t["is_default"] for t in r.context["tabs"]))


class RoleMatrixSaveTests(PermissionsBase):
    def test_save_writes_a_row_for_every_module(self):
        c = login(self.admin)
        matrix = pl.default_matrix(Role.CABO)
        matrix["eleitores"]["export"] = True
        matrix["mapa"] = {a: False for a in ACTIONS}
        r = self.save_role(c, "cabo", matrix)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], reverse("team:permissions") + "?aba=cabo")
        self.assertEqual(RolePermission.objects.filter(campaign=self.camp, role=Role.CABO).count(), len(MODULE_KEYS))
        saved = self.role_matrix(Role.CABO)
        self.assertEqual(saved, pl.normalize_matrix(matrix))
        self.assertTrue(saved["eleitores"]["export"])
        self.assertFalse(saved["mapa"]["view"])
        # a outra função não é tocada
        self.assertEqual(self.role_matrix(Role.COORDENADOR), pl.default_matrix(Role.COORDENADOR))

    def test_server_renormalizes_forged_input(self):
        c = login(self.admin)
        r = c.post(
            reverse("team:permissions_role_save", args=["cabo"]),
            {
                "perm__equipe__create": "on",  # sem "Ver": linha inteira zerada
                "perm__equipe__edit": "on",
                "perm__mapa__view": "on",
                "perm__mapa__delete": "on",  # ação que o módulo não suporta
                "perm__eleitores__view": "on",
                "perm__eleitores__export": "yes",  # valor estranho não vale
                "perm__modulo_falso__view": "on",
                "outro": "x",
            },
        )
        self.assertEqual(r.status_code, 302)
        saved = self.role_matrix(Role.CABO)
        self.assertFalse(any(saved["equipe"].values()))
        self.assertEqual({a for a, v in saved["mapa"].items() if v}, {"view"})
        self.assertTrue(saved["eleitores"]["view"])
        self.assertFalse(saved["eleitores"]["export"])
        self.assertFalse(RolePermission.objects.filter(module="modulo_falso").exists())
        row = RolePermission.objects.get(campaign=self.camp, role=Role.CABO, module="mapa")
        self.assertFalse(row.can_delete)

    def test_empty_post_turns_everything_off(self):
        self.save_role(login(self.admin), "cabo", {})
        self.assertFalse(any(any(row.values()) for row in self.role_matrix(Role.CABO).values()))

    def test_unknown_or_admin_role_is_404(self):
        c = login(self.admin)
        for slug in ("admin", "administrador", "super-admin", "xx"):
            self.assertEqual(c.post(reverse("team:permissions_role_save", args=[slug]), {}).status_code, 404, slug)
            self.assertEqual(c.post(reverse("team:permissions_role_reset", args=[slug]), {}).status_code, 404, slug)

    def test_audit_has_diff_summary_with_names_only(self):
        c = login(self.admin)
        matrix = pl.default_matrix(Role.CABO)
        matrix["eleitores"]["export"] = True
        matrix["mapa"] = {a: False for a in ACTIONS}
        self.save_role(c, "cabo", matrix)
        log = self.audits().get()
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.details["role"], Role.CABO)
        self.assertEqual(log.details["count"], 2)
        changes = {(x["module"], x["action"], x["to"]) for x in log.details["changes"]}
        self.assertEqual(changes, {("eleitores", "export", True), ("mapa", "view", False)})
        blob = json.dumps(log.details)
        for pii in ("admin@a.com", "Admin Alfa", "cabo@a.com"):
            self.assertNotIn(pii, blob)

    def test_saving_without_changes_is_reported(self):
        c = login(self.admin)
        r = self.save_role(c, "coordenador", pl.default_matrix(Role.COORDENADOR))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.audits().get().details["count"], 0)
        r = c.get(r["Location"])
        self.assertContains(r, "Nenhuma alteração")

    def test_change_takes_effect_immediately_for_the_affected_user(self):
        coord = login(self.coord)
        self.assertEqual(coord.get(reverse("team:create")).status_code, 200)
        self.assertEqual(coord.get(reverse("team:list")).status_code, 200)
        matrix = pl.default_matrix(Role.COORDENADOR)
        matrix["equipe"] = {a: False for a in ACTIONS}
        self.save_role(login(self.admin), "coordenador", matrix)
        self.assertEqual(coord.get(reverse("team:create")).status_code, 403)  # mesma sessão, sem novo login
        self.assertEqual(coord.get(reverse("team:list")).status_code, 403)
        # e o cabo, que não tinha equipe, passa a ver a lista (apenas ele mesmo)
        cabo = login(self.cabo)
        self.assertEqual(cabo.get(reverse("team:list")).status_code, 403)
        cabo_matrix = pl.default_matrix(Role.CABO)
        cabo_matrix["equipe"]["view"] = True
        self.save_role(login(self.admin), "cabo", cabo_matrix)
        self.assertEqual(cabo.get(reverse("team:list")).status_code, 200)
        self.assertTrue(can(permissions_for(self.cabo), "equipe", "view"))

    def test_isolation_between_campaigns(self):
        before_a = self.role_matrix(Role.CABO)
        matrix = pl.default_matrix(Role.CABO)
        matrix["eleitores"]["delete"] = True
        self.save_role(login(self.admin_b), "cabo", matrix)
        self.assertEqual(self.role_matrix(Role.CABO), before_a)
        self.assertTrue(self.role_matrix(Role.CABO, self.other)["eleitores"]["delete"])
        self.assertFalse(permissions_for(self.cabo)["eleitores"]["delete"])

    def test_reset_restores_defaults_and_audits(self):
        c = login(self.admin)
        matrix = pl.default_matrix(Role.COORDENADOR)
        matrix["whatsapp"] = {"view": True, "edit": True, **{a: False for a in ("create", "delete", "export")}}
        matrix["eleitores"]["delete"] = True
        self.save_role(c, "coordenador", matrix)
        self.assertNotEqual(self.role_matrix(Role.COORDENADOR), pl.default_matrix(Role.COORDENADOR))
        r = c.post(reverse("team:permissions_role_reset", args=["coordenador"]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.role_matrix(Role.COORDENADOR), pl.default_matrix(Role.COORDENADOR))
        self.assertEqual(RolePermission.objects.filter(campaign=self.camp, role=Role.COORDENADOR).count(), len(MODULE_KEYS))
        last = self.audits().latest("created_at")
        self.assertTrue(last.details["reset"])
        self.assertEqual(last.details["count"], 3)


class UserOverrideTests(PermissionsBase):
    def url(self, user=None):
        return reverse("team:permissions_user_save", args=[(user or self.cabo).pk])

    def post_ov(self, client, user=None, **cells):
        data = {f"ov__{k.replace('-', '__', 1)}": v for k, v in cells.items()}
        return client.post(self.url(user), data)

    def test_page_with_selected_user(self):
        c = login(self.admin)
        r = c.get(reverse("team:permissions"), {"usuario": str(self.cabo.pk)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["selected_user"], self.cabo)
        self.assertEqual(len(r.context["override_rows"]), len(MODULE_KEYS))
        self.assertContains(r, "Cabo Alfa")
        export = next(c_ for row in r.context["override_rows"] if row["key"] == "eleitores" for c_ in row["cells"] if c_["action"] == "export")
        self.assertEqual((export["value"], export["inherited"]), ("inherit", False))
        self.assertIn("override-config", r.content.decode())

    def test_page_never_shows_users_of_other_campaigns_or_admins(self):
        c = login(self.admin)
        for raw in (str(self.cabo_b.pk), str(self.admin.pk), str(uuid.uuid4()), "lixo", "' OR 1=1 --"):
            r = c.get(reverse("team:permissions"), {"usuario": raw})
            self.assertEqual(r.status_code, 200, raw)
            self.assertIsNone(r.context["selected_user"], raw)
            self.assertTrue(r.context["selected_missing"], raw)
            self.assertNotContains(r, "Cabo Beta Secreto")
        # a lista de escolha só traz coordenadores e cabos desta campanha
        r = c.get(reverse("team:permissions"))
        self.assertEqual({u.pk for u in r.context["configurable_users"]}, {self.coord.pk, self.cabo.pk})

    def test_tri_state_save_and_immediate_effect(self):
        cabo_client = login(self.cabo)
        self.assertEqual(cabo_client.get(reverse("team:list")).status_code, 403)
        admin_client = login(self.admin)
        r = self.post_ov(
            admin_client,
            **{"eleitores-export": "allow", "eleitores-create": "deny", "equipe-create": "allow", "dashboard-view": "deny"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"usuario={self.cabo.pk}", r["Location"])
        self.assertTrue(r["Location"].endswith("#excecoes"))
        rows = {p.module: p for p in UserPermission.objects.filter(user=self.cabo)}
        self.assertEqual(set(rows), {"eleitores", "equipe", "dashboard"})
        self.assertIs(rows["eleitores"].can_export, True)
        self.assertIs(rows["eleitores"].can_create, False)
        self.assertIsNone(rows["eleitores"].can_view)
        self.assertIs(rows["equipe"].can_create, True)
        self.assertIs(rows["equipe"].can_view, True)  # permitir ação num módulo que o papel não vê liga "Ver"
        self.assertIs(rows["dashboard"].can_view, False)
        perms = permissions_for(self.cabo)
        self.assertTrue(can(perms, "eleitores", "export"))
        self.assertFalse(can(perms, "eleitores", "create"))
        self.assertTrue(can(perms, "eleitores", "edit"))  # herdado
        self.assertFalse(can(perms, "dashboard", "view"))
        # efeito imediato na sessão já aberta do cabo (ganhou "equipe": vê a lista, só ele mesmo)
        r = cabo_client.get(reverse("team:list"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x.email for x in r.context["page_obj"]], ["cabo@a.com"])
        # mesmo com equipe.create por exceção, cabo nunca cadastra membros
        self.assertEqual(cabo_client.get(reverse("team:create")).status_code, 403)
        # as permissões do papel e de outros usuários não mudam
        self.assertFalse(self.role_matrix(Role.CABO)["eleitores"]["export"])
        self.assertFalse(UserPermission.objects.filter(user=self.coord).exists())

    def test_deny_view_clears_the_other_cells_of_the_module(self):
        c = login(self.admin)
        self.post_ov(c, **{"eleitores-view": "deny", "eleitores-export": "allow", "eleitores-create": "allow"})
        row = UserPermission.objects.get(user=self.cabo, module="eleitores")
        self.assertEqual((row.can_view, row.can_create, row.can_export), (False, None, None))
        self.assertFalse(can(permissions_for(self.cabo), "eleitores", "create"))

    def test_all_inherit_deletes_rows(self):
        c = login(self.admin)
        self.post_ov(c, **{"eleitores-export": "allow", "mapa-view": "deny"})
        self.assertEqual(UserPermission.objects.filter(user=self.cabo).count(), 2)
        self.post_ov(c, **{"eleitores-export": "inherit"})
        self.assertFalse(UserPermission.objects.filter(user=self.cabo).exists())
        self.assertEqual(self.audits().count(), 2)

    def test_partial_update_replaces_previous_exceptions(self):
        c = login(self.admin)
        self.post_ov(c, **{"eleitores-export": "allow", "mapa-view": "deny"})
        self.post_ov(c, **{"mapa-view": "deny"})
        modules = set(UserPermission.objects.filter(user=self.cabo).values_list("module", flat=True))
        self.assertEqual(modules, {"mapa"})

    def test_clear_button_removes_everything(self):
        c = login(self.admin)
        self.post_ov(c, **{"eleitores-export": "allow", "mapa-view": "deny"})
        r = c.post(self.url(), {"clear": "1", "ov__eleitores__export": "allow"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(UserPermission.objects.filter(user=self.cabo).exists())
        self.assertTrue(self.audits().latest("created_at").details["cleared"])

    def test_garbage_values_are_treated_as_inherit(self):
        c = login(self.admin)
        r = c.post(self.url(), {"ov__eleitores__export": "talvez", "ov__mapa__delete": "allow", "ov__falso__view": "allow"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(UserPermission.objects.exists())

    def test_targets_are_validated_against_campaign_and_role(self):
        c = login(self.admin)
        for target in (self.admin, self.admin_b, self.cabo_b):
            r = c.post(self.url(target), {"ov__eleitores__export": "allow"})
            self.assertEqual(r.status_code, 404, target.email)
        self.assertEqual(c.post(reverse("team:permissions_user_save", args=[uuid.uuid4()]), {}).status_code, 404)
        self.assertEqual(c.post("/painel/permissoes/usuario/lixo/", {}).status_code, 404)
        self.assertFalse(UserPermission.objects.exists())
        # o admin da outra campanha também não alcança usuários daqui
        self.assertEqual(login(self.admin_b).post(self.url(), {"ov__eleitores__export": "allow"}).status_code, 404)
        self.assertFalse(UserPermission.objects.exists())

    def test_list_of_users_with_exceptions(self):
        c = login(self.admin)
        self.post_ov(c, **{"eleitores-export": "allow", "mapa-view": "deny"})
        self.post_ov(c, self.coord, **{"dashboard-delete": "deny"})
        UserPermission.objects.create(user=self.cabo_b, module="mapa", can_view=False)  # outra campanha
        r = c.get(reverse("team:permissions"))
        listed = {item["user"].email: item["count"] for item in r.context["users_with_overrides"]}
        self.assertEqual(listed, {"cabo@a.com": 2, "coord@a.com": 1})
        self.assertNotContains(r, "Cabo Beta Secreto")

    def test_audit_for_user_exceptions_has_only_ids_and_names_of_permissions(self):
        c = login(self.admin)
        self.post_ov(c, **{"eleitores-export": "allow"})
        log = self.audits().get()
        self.assertEqual(log.entity, "User")
        self.assertEqual(log.entity_id, str(self.cabo.pk))
        self.assertEqual(log.details["scope"], "user")
        self.assertEqual(log.details["changes"], [{"module": "eleitores", "action": "export", "from": None, "to": True}])
        blob = json.dumps(log.details)
        for pii in ("cabo@a.com", "Cabo Alfa", "admin@a.com"):
            self.assertNotIn(pii, blob)

    def test_inactive_target_can_still_be_configured(self):
        self.cabo.is_active = False
        self.cabo.save()
        r = self.post_ov(login(self.admin), **{"eleitores-export": "allow"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(UserPermission.objects.filter(user=self.cabo).exists())
