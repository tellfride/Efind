"""Regras de acesso aos dashboards: quem vê, edita, exclui, compartilha e define padrão (lógica pura)."""

from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from apps.core.constants import Role
from apps.core.permissions import default_permissions_for, full_permissions, no_permissions
from apps.dashboards import rules

CAMPAIGN = "camp-1"


def user(role, id_="u1", campaign=CAMPAIGN):
    return NS(pk=id_, id=id_, role=role, campaign_id=campaign)


def dash(owner="u1", shared=False, is_default=False, campaign=CAMPAIGN, name="Painel"):
    return NS(campaign_id=campaign, owner_id=owner, shared=shared, is_default=is_default, name=name)


ADMIN = user(Role.ADMIN, "adm")
COORD = user(Role.COORDENADOR, "coo")
CABO = user(Role.CABO, "cab")
ADMIN_PERMS = full_permissions()
COORD_PERMS = default_permissions_for(Role.COORDENADOR)  # dashboard: view, create, edit, delete
CABO_PERMS = default_permissions_for(Role.CABO)  # dashboard: somente view


class VisibilityTests(SimpleTestCase):
    def test_shared_and_own_dashboards_are_visible(self):
        self.assertTrue(rules.is_visible(COORD, COORD_PERMS, dash(owner=None, shared=True)))
        self.assertTrue(rules.is_visible(COORD, COORD_PERMS, dash(owner="coo")))

    def test_private_dashboard_of_someone_else_is_invisible_even_to_admin(self):
        self.assertFalse(rules.is_visible(COORD, COORD_PERMS, dash(owner="cab")))
        self.assertFalse(rules.is_visible(ADMIN, ADMIN_PERMS, dash(owner="coo")))

    def test_other_campaign_is_invisible(self):
        self.assertFalse(rules.is_visible(ADMIN, ADMIN_PERMS, dash(owner="adm", campaign="outra")))
        self.assertFalse(rules.is_visible(ADMIN, ADMIN_PERMS, dash(owner=None, shared=True, campaign="outra")))

    def test_requires_view_permission(self):
        self.assertFalse(rules.is_visible(CABO, no_permissions(), dash(owner=None, shared=True)))
        self.assertTrue(rules.is_visible(CABO, CABO_PERMS, dash(owner=None, shared=True)))


class EditDeleteTests(SimpleTestCase):
    def test_admin_edits_and_deletes_any_visible_dashboard(self):
        for d in (dash(owner=None, shared=True), dash(owner="coo", shared=True), dash(owner="adm")):
            self.assertTrue(rules.can_edit(ADMIN, ADMIN_PERMS, d))
            self.assertTrue(rules.can_delete(ADMIN, ADMIN_PERMS, d))

    def test_admin_cannot_touch_private_dashboard_of_others(self):
        d = dash(owner="coo")
        self.assertFalse(rules.can_edit(ADMIN, ADMIN_PERMS, d))
        self.assertFalse(rules.can_delete(ADMIN, ADMIN_PERMS, d))

    def test_coordinator_edits_and_deletes_only_own_private_dashboards(self):
        own = dash(owner="coo")
        self.assertTrue(rules.can_edit(COORD, COORD_PERMS, own))
        self.assertTrue(rules.can_delete(COORD, COORD_PERMS, own))

    def test_shared_or_ownerless_dashboards_are_admin_only(self):
        for d in (dash(owner="coo", shared=True), dash(owner=None, shared=True), dash(owner=None, shared=False)):
            self.assertFalse(rules.can_edit(COORD, COORD_PERMS, d))
            self.assertFalse(rules.can_delete(COORD, COORD_PERMS, d))

    def test_other_users_dashboards_cannot_be_edited(self):
        self.assertFalse(rules.can_edit(COORD, COORD_PERMS, dash(owner="cab")))
        self.assertFalse(rules.can_delete(COORD, COORD_PERMS, dash(owner="cab")))

    def test_edit_and_delete_need_their_own_permission(self):
        own = dash(owner="cab")
        self.assertFalse(rules.can_edit(CABO, CABO_PERMS, own))  # cabo só tem dashboard.view por padrão
        self.assertFalse(rules.can_delete(CABO, CABO_PERMS, own))
        edit_only = {**CABO_PERMS, "dashboard": {**CABO_PERMS["dashboard"], "edit": True}}
        self.assertTrue(rules.can_edit(CABO, edit_only, own))
        self.assertFalse(rules.can_delete(CABO, edit_only, own))

    def test_duplicate_needs_create_permission_and_visibility(self):
        shared = dash(owner=None, shared=True)
        self.assertTrue(rules.can_duplicate(COORD, COORD_PERMS, shared))
        self.assertFalse(rules.can_duplicate(CABO, CABO_PERMS, shared))
        self.assertFalse(rules.can_duplicate(COORD, COORD_PERMS, dash(owner="cab")))


class SharingAndDefaultTests(SimpleTestCase):
    def test_only_admin_can_share(self):
        self.assertTrue(rules.can_share(ADMIN))
        self.assertFalse(rules.can_share(COORD))
        self.assertFalse(rules.can_share(CABO))

    def test_my_default_only_for_own_private_dashboards(self):
        self.assertTrue(rules.can_set_my_default(COORD, COORD_PERMS, dash(owner="coo")))
        self.assertFalse(rules.can_set_my_default(COORD, COORD_PERMS, dash(owner="coo", shared=True)))
        self.assertFalse(rules.can_set_my_default(COORD, COORD_PERMS, dash(owner=None, shared=True)))
        self.assertFalse(rules.can_set_my_default(COORD, COORD_PERMS, dash(owner="cab")))
        self.assertTrue(rules.can_set_my_default(CABO, CABO_PERMS, dash(owner="cab")))  # basta ver o próprio

    def test_default_flags(self):
        self.assertTrue(rules.is_campaign_default(dash(owner=None, shared=True, is_default=True)))
        self.assertFalse(rules.is_campaign_default(dash(owner="coo", is_default=True)))
        self.assertTrue(rules.is_personal_default(dash(owner="coo", is_default=True), "coo"))
        self.assertFalse(rules.is_personal_default(dash(owner="coo", is_default=True), "outro"))
        self.assertFalse(rules.is_personal_default(dash(owner="coo", shared=True, is_default=True), "coo"))

    def test_resolve_sharing_ignores_non_admin_requests(self):
        current = dash(owner="coo")
        result = rules.resolve_sharing(COORD, current, shared=True, campaign_default=True)
        self.assertEqual(result, {"shared": False, "is_default": False, "owner_id": "coo"})

    def test_resolve_sharing_for_admin(self):
        private = dash(owner="adm")
        self.assertEqual(rules.resolve_sharing(ADMIN, private, shared=True, campaign_default=False),
                         {"shared": True, "is_default": False, "owner_id": "adm"})  # fmt: skip
        # padrão da campanha implica compartilhado
        self.assertEqual(rules.resolve_sharing(ADMIN, private, shared=False, campaign_default=True),
                         {"shared": True, "is_default": True, "owner_id": "adm"})  # fmt: skip

    def test_admin_unsharing_an_ownerless_dashboard_becomes_its_owner(self):
        template = dash(owner=None, shared=True, is_default=True)
        result = rules.resolve_sharing(ADMIN, template, shared=False, campaign_default=False)
        self.assertEqual(result, {"shared": False, "is_default": False, "owner_id": "adm"})

    def test_unsharing_keeps_a_personal_default(self):
        personal = dash(owner="adm", is_default=True)
        result = rules.resolve_sharing(ADMIN, personal, shared=False, campaign_default=False)
        self.assertTrue(result["is_default"])


class HomeChoiceTests(SimpleTestCase):
    def test_home_prefers_my_default_then_campaign_default_then_first(self):
        campaign_default = dash(owner=None, shared=True, is_default=True, name="Padrão")
        other = dash(owner=None, shared=True, name="Outro")
        mine = dash(owner="coo", is_default=True, name="Meu")
        self.assertIs(rules.pick_home_dashboard([other, campaign_default, mine], "coo"), mine)
        self.assertIs(rules.pick_home_dashboard([other, campaign_default], "coo"), campaign_default)
        self.assertIs(rules.pick_home_dashboard([other], "coo"), other)
        self.assertIsNone(rules.pick_home_dashboard([], "coo"))

    def test_sort_order(self):
        campaign_default = dash(owner=None, shared=True, is_default=True, name="Zeta")
        mine = dash(owner="coo", is_default=True, name="Beta")
        shared = dash(owner=None, shared=True, name="Alfa")
        private = dash(owner="coo", name="Gama")
        ordered = rules.sort_dashboards([private, shared, mine, campaign_default], "coo")
        self.assertEqual([d.name for d in ordered], ["Zeta", "Beta", "Alfa", "Gama"])
