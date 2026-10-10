"""Telas e ações da equipe: acesso por papel, cadastro, perfil, edição, ativar/desativar, senha, link, mover e excluir."""

import datetime as dt

from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import RolePermission, User, UserPermission
from apps.auditlog.models import AuditLog
from apps.core.constants import Role
from apps.team import services
from apps.team.services import TeamError
from apps.voters.models import Voter

from .helpers import PASSWORD, fast_hashers, login, make_campaign, make_user, make_voter


@fast_hashers
class BaseTeamTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.camp = make_campaign("alfa")
        cls.other = make_campaign("beta")
        cls.admin = make_user(cls.camp, "admin@a.com", Role.ADMIN, name="Admin Alfa")
        cls.coord1 = make_user(cls.camp, "coord1@a.com", Role.COORDENADOR, parent=cls.admin, name="Coord Um")
        cls.coord2 = make_user(cls.camp, "coord2@a.com", Role.COORDENADOR, parent=cls.admin, name="Coord Dois")
        cls.cabo1 = make_user(cls.camp, "cabo1@a.com", Role.CABO, parent=cls.coord1, name="Cabo Um", goal=10, phone="5511988880001")
        cls.cabo2 = make_user(cls.camp, "cabo2@a.com", Role.CABO, parent=cls.coord2, name="Cabo Dois")
        cls.admin_b = make_user(cls.other, "admin@b.com", Role.ADMIN, name="Admin Beta")
        cls.coord_b = make_user(cls.other, "coord@b.com", Role.COORDENADOR, parent=cls.admin_b, name="Coord Beta")
        cls.cabo_b = make_user(cls.other, "cabo@b.com", Role.CABO, parent=cls.coord_b, name="Cabo Beta")

    def audit(self, action):
        return AuditLog.objects.filter(campaign=self.camp, action=action)

    def create_payload(self, **overrides):
        data = {
            "name": "Novo Membro",
            "email": "novo@a.com",
            "phone": "(11) 98765-4321",
            "role": "CABO",
            "parent": str(self.coord1.pk),
            "goal": "50",
            "region": "Zona Norte",
        }
        data.update(overrides)
        return data

    def grant(self, role, module, **flags):
        RolePermission.objects.filter(campaign=self.camp, role=role, module=module).update(**flags)


class AccessTests(BaseTeamTest):
    def urls(self):
        return [
            reverse("team:list"),
            reverse("team:create"),
            reverse("team:detail", args=[self.cabo1.pk]),
        ]

    def test_anonymous_goes_to_login(self):
        for url in self.urls():
            r = Client().get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r["Location"].startswith("/login/"), url)

    def test_admin_and_coordinator_pages(self):
        for user in (self.admin, self.coord1):
            c = login(user)
            for url in self.urls()[:2]:
                self.assertEqual(c.get(url).status_code, 200, (user.role, url))
        self.assertEqual(login(self.admin).get(reverse("team:detail", args=[self.cabo1.pk])).status_code, 200)
        self.assertEqual(login(self.coord1).get(reverse("team:detail", args=[self.cabo1.pk])).status_code, 200)
        self.assertEqual(login(self.coord1).get(reverse("team:detail", args=[self.coord1.pk])).status_code, 200)

    def test_cabo_without_module_is_forbidden(self):
        c = login(self.cabo1)
        for url in self.urls():
            self.assertEqual(c.get(url).status_code, 403, url)

    def test_super_admin_is_sent_to_super_area(self):
        sup = User.objects.create_superuser("super@x.com", PASSWORD)
        r = login(sup).get(reverse("team:list"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/super/")

    def test_cabo_with_view_sees_only_himself_but_cannot_register(self):
        self.grant(Role.CABO, "equipe", can_view=True, can_create=True, can_edit=True, can_delete=True)
        c = login(self.cabo1)
        r = c.get(reverse("team:list"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([row.email for row in r.context["page_obj"]], ["cabo1@a.com"])
        self.assertFalse(r.context["can_create"])
        self.assertContains(r, "Cabo Um")
        self.assertNotContains(r, "Cabo Dois")
        self.assertNotContains(r, "Coord Dois")
        # mesmo com "criar" configurado, cabo nunca cadastra
        self.assertEqual(c.get(reverse("team:create")).status_code, 403)
        self.assertEqual(c.post(reverse("team:create"), self.create_payload()).status_code, 403)
        self.assertFalse(User.objects.filter(email="novo@a.com").exists())
        # nem gerencia os outros
        self.assertEqual(c.get(reverse("team:detail", args=[self.cabo2.pk])).status_code, 404)
        self.assertEqual(c.post(reverse("team:update", args=[self.cabo1.pk]), {"name": "Outro nome"}).status_code, 403)
        self.assertEqual(c.post(reverse("team:delete", args=[self.cabo1.pk])).status_code, 403)

    def test_post_only_actions_reject_get(self):
        c = login(self.admin)
        for name in ("update", "move", "activate", "deactivate", "reset_password", "regenerate_link", "delete"):
            r = c.get(reverse(f"team:{name}", args=[self.cabo1.pk]))
            self.assertEqual(r.status_code, 405, name)

    def test_csrf_is_enforced_on_state_changes(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        r = c.post(reverse("team:deactivate", args=[self.cabo1.pk]))
        self.assertEqual(r.status_code, 403)
        self.cabo1.refresh_from_db()
        self.assertTrue(self.cabo1.is_active)
        self.assertEqual(c.post(reverse("team:create"), self.create_payload()).status_code, 403)

    def test_names_are_escaped(self):
        evil = make_user(self.camp, "evil@a.com", Role.CABO, parent=self.coord1, name="<script>alert(1)</script>")
        c = login(self.admin)
        for url in (reverse("team:list"), reverse("team:list") + "?vista=lista", reverse("team:detail", args=[evil.pk])):
            r = c.get(url)
            self.assertNotContains(r, "<script>alert(1)</script>")
            self.assertContains(r, "&lt;script&gt;alert(1)&lt;/script&gt;")


class ListTests(BaseTeamTest):
    def test_admin_list_context(self):
        make_voter(self.camp, self.cabo1, 1)
        r = login(self.admin).get(reverse("team:list"))
        s = r.context["summary"]
        self.assertEqual((s.total, s.admins, s.coordinators, s.cabos, s.voters), (5, 1, 2, 2, 1))
        self.assertEqual(r.context["initial_view"], "hierarquia")
        self.assertEqual(len(r.context["tree"]), 1)
        self.assertNotContains(r, "Admin Beta")
        self.assertContains(r, "Novo membro")

    def test_filters_and_sorting_in_list_view(self):
        for i in range(3):
            make_voter(self.camp, self.cabo2, i + 1)
        c = login(self.admin)
        r = c.get(reverse("team:list"), {"papel": "CABO", "ordem": "eleitores"})
        self.assertEqual(r.context["initial_view"], "lista")
        self.assertEqual([x.email for x in r.context["page_obj"]], ["cabo2@a.com", "cabo1@a.com"])
        r = c.get(reverse("team:list"), {"q": "coord um"})
        self.assertEqual([x.email for x in r.context["page_obj"]], ["coord1@a.com"])
        r = c.get(reverse("team:list"), {"coord": str(self.coord1.pk)})
        self.assertEqual({x.email for x in r.context["page_obj"]}, {"coord1@a.com", "cabo1@a.com"})
        self.cabo1.is_active = False
        self.cabo1.save()
        r = c.get(reverse("team:list"), {"status": "inativos"})
        self.assertEqual([x.email for x in r.context["page_obj"]], ["cabo1@a.com"])

    def test_coordinator_filter_never_accepts_foreign_coordinator(self):
        r = login(self.admin).get(reverse("team:list"), {"coord": str(self.coord_b.pk)})
        self.assertEqual(r.context["filters"].coordinator, "")
        self.assertNotContains(r, "Coord Beta")

    def test_coordinator_sees_only_own_network(self):
        r = login(self.coord1).get(reverse("team:list"))
        self.assertEqual({row.email for row in r.context["page_obj"]}, {"coord1@a.com", "cabo1@a.com"})
        self.assertNotContains(r, "Cabo Dois")
        self.assertNotContains(r, "Coord Dois")
        self.assertFalse(r.context["show_coordinator_filter"])

    def test_malformed_query_params_do_not_break(self):
        c = login(self.admin)
        r = c.get(reverse("team:list"), {"page": "abc", "ordem": "'; drop", "papel": "x", "coord": "não-uuid"})
        self.assertEqual(r.status_code, 200)


class CreateTests(BaseTeamTest):
    def test_admin_creates_cabo_and_credentials_are_shown_once(self):
        c = login(self.admin)
        r = c.post(reverse("team:create"), self.create_payload())
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "team/credentials.html")
        member = User.objects.get(email="novo@a.com")
        self.assertEqual((member.role, member.parent_id, member.campaign_id, member.goal), (Role.CABO, self.coord1.pk, self.camp.pk, 50))
        self.assertEqual((member.phone, member.region, member.name), ("5511987654321", "Zona Norte", "Novo Membro"))
        password = r.context["password"]
        self.assertTrue(member.check_password(password))
        self.assertContains(r, password)
        self.assertContains(r, member.invite_code)
        self.assertTrue(r.context["whatsapp_url"].startswith("https://wa.me/5511987654321?text="))
        self.assertIn("no-store", r["Cache-Control"])
        # a senha nunca é gravada em texto: nem no hash, nem na auditoria
        self.assertNotIn(password, member.password)
        log = self.audit("user.create").get()
        self.assertEqual(log.entity_id, str(member.pk))
        blob = str(log.details)
        for secret in (password, "novo@a.com", "Novo Membro", "987654321"):
            self.assertNotIn(secret, blob)
        # recarregar a lista não mostra a senha
        self.assertNotContains(c.get(reverse("team:list")), password)

    def test_admin_with_given_password(self):
        c = login(self.admin)
        r = c.post(reverse("team:create"), self.create_payload(password="Escolhida2026"))
        self.assertEqual(r.context["password"], "Escolhida2026")
        self.assertTrue(User.objects.get(email="novo@a.com").check_password("Escolhida2026"))

    def test_weak_password_is_rejected(self):
        c = login(self.admin)
        for pw in ("12345678", "abcdefgh", "ab1"):
            r = c.post(reverse("team:create"), self.create_payload(password=pw))
            self.assertEqual(r.status_code, 200, pw)
            self.assertIn("password", r.context["form"].errors, pw)
        self.assertFalse(User.objects.filter(email="novo@a.com").exists())

    def test_admin_creates_each_role(self):
        c = login(self.admin)
        r = c.post(reverse("team:create"), self.create_payload(email="adm2@a.com", role="ADMIN", parent=""))
        self.assertEqual(r.status_code, 200)
        adm = User.objects.get(email="adm2@a.com")
        self.assertEqual((adm.role, adm.parent_id), (Role.ADMIN, None))
        r = c.post(reverse("team:create"), self.create_payload(email="co@a.com", role="COORDENADOR", parent=""))
        co = User.objects.get(email="co@a.com")
        self.assertEqual((co.role, co.parent_id), (Role.COORDENADOR, self.admin.pk))  # padrão: o próprio admin
        c.post(reverse("team:create"), self.create_payload(email="co2@a.com", role="COORDENADOR", parent=str(adm.pk)))
        self.assertEqual(User.objects.get(email="co2@a.com").parent_id, adm.pk)

    def test_cabo_needs_a_coordinator_when_they_exist(self):
        c = login(self.admin)
        r = c.post(reverse("team:create"), self.create_payload(parent=""))
        self.assertEqual(r.status_code, 200)
        self.assertIn("parent", r.context["form"].errors)
        r = c.post(reverse("team:create"), self.create_payload(parent=str(self.admin.pk)))
        self.assertIn("parent", r.context["form"].errors)
        self.assertFalse(User.objects.filter(email="novo@a.com").exists())

    def test_cabo_below_admin_when_there_are_no_active_coordinators(self):
        User.objects.filter(role=Role.COORDENADOR, campaign=self.camp).update(is_active=False)
        c = login(self.admin)
        r = c.post(reverse("team:create"), self.create_payload(parent=""))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.get(email="novo@a.com").parent_id, self.admin.pk)

    def test_inactive_coordinator_cannot_be_chosen(self):
        self.coord2.is_active = False
        self.coord2.save()
        r = login(self.admin).post(reverse("team:create"), self.create_payload(parent=str(self.coord2.pk)))
        self.assertIn("parent", r.context["form"].errors)

    def test_parent_from_another_campaign_is_rejected(self):
        c = login(self.admin)
        for parent in (self.coord_b.pk, self.admin_b.pk, "nao-e-uuid"):
            r = c.post(reverse("team:create"), self.create_payload(parent=str(parent)))
            self.assertEqual(r.status_code, 200, parent)
            self.assertIn("parent", r.context["form"].errors, parent)
        c.post(reverse("team:create"), self.create_payload(role="COORDENADOR", parent=str(self.admin_b.pk)))
        self.assertFalse(User.objects.filter(email="novo@a.com").exists())

    def test_email_must_be_unique_ignoring_case_and_across_campaigns(self):
        c = login(self.admin)
        for email in ("CABO1@A.COM", "admin@b.com", " Cabo1@a.com "):
            r = c.post(reverse("team:create"), self.create_payload(email=email))
            self.assertEqual(r.status_code, 200, email)
            self.assertIn("email", r.context["form"].errors, email)
            self.assertContains(r, "já está cadastrado")
        self.assertEqual(User.objects.filter(email__iexact="cabo1@a.com").count(), 1)

    def test_invalid_input(self):
        c = login(self.admin)
        for bad in ({"name": "Ab"}, {"email": "sem-arroba"}, {"phone": "123"}, {"goal": "-5"}, {"goal": "abc"}, {"role": "SUPER_ADMIN"}):
            r = c.post(reverse("team:create"), self.create_payload(**bad))
            self.assertEqual(r.status_code, 200, bad)
            self.assertTrue(r.context["form"].errors, bad)
        self.assertFalse(User.objects.filter(email="novo@a.com").exists())

    def test_coordinator_creates_cabo_forced_below_himself(self):
        c = login(self.coord1)
        r = c.post(reverse("team:create"), self.create_payload(parent=str(self.coord2.pk)))  # parent forjado
        self.assertEqual(r.status_code, 200)
        member = User.objects.get(email="novo@a.com")
        self.assertEqual((member.role, member.parent_id), (Role.CABO, self.coord1.pk))
        # sem role/parent no POST também funciona (campos nem existem para ele)
        data = self.create_payload(email="outro@a.com")
        del data["role"], data["parent"]
        c.post(reverse("team:create"), data)
        self.assertEqual(User.objects.get(email="outro@a.com").parent_id, self.coord1.pk)

    def test_coordinator_cannot_forge_coordinator_or_admin(self):
        c = login(self.coord1)
        for role in ("COORDENADOR", "ADMIN"):
            email = f"forjado-{role.lower()}@a.com"
            r = c.post(reverse("team:create"), self.create_payload(role=role, email=email))
            self.assertEqual(r.status_code, 200, role)
            self.assertTrue(r.context["form"].errors, role)
            self.assertFalse(User.objects.filter(email=email).exists(), role)

    def test_coordinator_form_hides_role_and_parent(self):
        r = login(self.coord1).get(reverse("team:create"))
        self.assertNotIn("parent", r.context["form"].fields)
        self.assertNotContains(r, 'name="role"')
        self.assertNotContains(r, 'name="parent"')
        r = login(self.admin).get(reverse("team:create"))
        self.assertContains(r, 'name="role"')
        self.assertContains(r, 'name="parent"')

    def test_coordinator_without_create_permission_is_forbidden(self):
        self.grant(Role.COORDENADOR, "equipe", can_create=False)
        c = login(self.coord1)
        self.assertEqual(c.get(reverse("team:create")).status_code, 403)
        self.assertEqual(c.post(reverse("team:create"), self.create_payload()).status_code, 403)
        self.assertFalse(User.objects.filter(email="novo@a.com").exists())

    def test_member_without_phone_has_no_whatsapp_link(self):
        r = login(self.admin).post(reverse("team:create"), self.create_payload(phone=""))
        self.assertEqual(r.context["whatsapp_url"], "")


class DetailTests(BaseTeamTest):
    def setUp(self):
        old = make_voter(self.camp, self.cabo1, 1, neighborhood="Centro")
        Voter.objects.filter(pk=old.pk).update(created_at=timezone.now() - dt.timedelta(days=20))
        make_voter(self.camp, self.cabo1, 2, neighborhood="Centro")
        make_voter(self.camp, self.cabo1, 3, neighborhood="Cambuí")
        make_voter(self.camp, self.cabo2, 4, neighborhood="Outro")

    def test_stats_neighborhoods_and_recent(self):
        r = login(self.admin).get(reverse("team:detail", args=[self.cabo1.pk]))
        self.assertEqual(r.status_code, 200)
        stats = r.context["stats"]
        self.assertEqual((stats["total"], stats["today"], stats["d7"], stats["d30"]), (3, 2, 2, 3))
        self.assertEqual(r.context["neighborhoods"][0]["name"], "Centro")
        self.assertEqual(r.context["neighborhoods"][0]["count"], 2)
        self.assertEqual(len(r.context["recent_voters"]), 3)
        self.assertEqual(r.context["goal_remaining"], 7)
        self.assertEqual(round(r.context["goal_percent"]), 30)
        self.assertContains(r, "data:image/png;base64,")
        self.assertContains(r, self.cabo1.invite_code)
        self.assertNotContains(r, "Outro")  # bairro de outro cabo

    def test_recent_voters_hidden_without_voters_permission(self):
        self.grant(Role.COORDENADOR, "eleitores", can_view=False, can_create=False, can_edit=False, can_export=False)
        r = login(self.coord1).get(reverse("team:detail", args=[self.cabo1.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["can_see_voters"])
        self.assertEqual(r.context["recent_voters"], [])
        self.assertNotContains(r, "Eleitor 2")

    def test_recent_voters_visible_with_permission(self):
        r = login(self.coord1).get(reverse("team:detail", args=[self.cabo1.pk]))
        self.assertTrue(r.context["can_see_voters"])
        self.assertContains(r, "Eleitor 2")

    def test_coordinator_lists_his_cabos(self):
        r = login(self.admin).get(reverse("team:detail", args=[self.coord1.pk]))
        children = r.context["children"]
        self.assertEqual([(i["member"].email, i["voters"]) for i in children], [("cabo1@a.com", 3)])

    def test_scope_and_campaign_isolation(self):
        c = login(self.coord1)
        for member in (self.cabo2, self.coord2, self.admin, self.admin_b, self.cabo_b):
            self.assertEqual(c.get(reverse("team:detail", args=[member.pk])).status_code, 404, member.email)
        for member in (self.admin_b, self.coord_b, self.cabo_b):
            self.assertEqual(login(self.admin).get(reverse("team:detail", args=[member.pk])).status_code, 404, member.email)
        import uuid

        self.assertEqual(login(self.admin).get(reverse("team:detail", args=[uuid.uuid4()])).status_code, 404)
        self.assertEqual(login(self.admin).get("/painel/equipe/nao-e-uuid/").status_code, 404)

    def test_action_buttons_follow_permissions(self):
        r = login(self.coord1).get(reverse("team:detail", args=[self.cabo1.pk]))
        self.assertTrue(r.context["show_edit"])
        self.assertTrue(r.context["show_regenerate"])
        self.assertFalse(r.context["show_delete"])  # coordenador não exclui por padrão
        self.assertEqual(r.context["move_options"], [])
        r = login(self.admin).get(reverse("team:detail", args=[self.cabo1.pk]))
        self.assertTrue(r.context["show_delete"] and r.context["show_active_toggle"])
        self.assertEqual({u.pk for u in r.context["move_options"]}, {self.coord1.pk, self.coord2.pk})
        r = login(self.admin).get(reverse("team:detail", args=[self.admin.pk]))
        self.assertFalse(r.context["show_delete"] or r.context["show_active_toggle"] or r.context["show_reset_password"])
        self.assertTrue(r.context["is_last_admin"])


class EditTests(BaseTeamTest):
    def post_update(self, client, member, **data):
        base = {"name": member.name, "email": member.email, "phone": "", "goal": "", "region": ""}
        base.update(data)
        return client.post(reverse("team:update", args=[member.pk]), base)

    def test_coordinator_edits_basic_fields_of_his_cabo(self):
        r = self.post_update(login(self.coord1), self.cabo1, name="Cabo Renomeado", phone="(11) 91234-5678", goal="77", region="Sul")
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertEqual((self.cabo1.name, self.cabo1.phone, self.cabo1.goal, self.cabo1.region), ("Cabo Renomeado", "5511912345678", 77, "Sul"))
        self.assertTrue(self.audit("user.update").exists())

    def test_coordinator_cannot_change_email_role_parent_or_status(self):
        r = self.post_update(
            login(self.coord1),
            self.cabo1,
            email="hacker@x.com",
            role="COORDENADOR",
            parent=str(self.coord2.pk),
            is_active="",
        )
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertEqual(
            (self.cabo1.email, self.cabo1.role, self.cabo1.parent_id, self.cabo1.is_active),
            ("cabo1@a.com", Role.CABO, self.coord1.pk, True),
        )

    def test_coordinator_cannot_edit_outside_his_network(self):
        c = login(self.coord1)
        self.assertEqual(self.post_update(c, self.cabo2, name="Invadido").status_code, 404)
        self.assertEqual(self.post_update(c, self.admin_b, name="Invadido").status_code, 404)
        self.assertEqual(self.post_update(c, self.coord1, name="Eu mesmo").status_code, 403)  # perfil próprio: Meu perfil
        self.cabo2.refresh_from_db()
        self.assertEqual(self.cabo2.name, "Cabo Dois")

    def test_admin_changes_email_and_duplicates_are_rejected(self):
        c = login(self.admin)
        self.assertEqual(self.post_update(c, self.cabo1, email="Novo.Email@A.com").status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertEqual(self.cabo1.email, "novo.email@a.com")
        r = self.post_update(c, self.cabo1, email="CABO2@a.com")
        self.assertEqual(r.status_code, 200)
        self.assertIn("email", r.context["edit_form"].errors)
        r = self.post_update(c, self.cabo1, email="admin@b.com")
        self.assertIn("email", r.context["edit_form"].errors)
        self.assertTrue(r.context["edit_open"])

    def test_admin_promotes_cabo_to_coordinator_and_drops_overrides(self):
        UserPermission.objects.create(user=self.cabo1, module="eleitores", can_export=True)
        r = self.post_update(login(self.admin), self.cabo1, role="COORDENADOR", parent=str(self.admin.pk))
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertEqual((self.cabo1.role, self.cabo1.parent_id), (Role.COORDENADOR, self.admin.pk))
        self.assertFalse(UserPermission.objects.filter(user=self.cabo1).exists())
        log = self.audit("user.update").latest("created_at")
        self.assertEqual(log.details["role_from"], Role.CABO)
        self.assertEqual(log.details["role_to"], Role.COORDENADOR)

    def test_coordinator_with_cabos_cannot_become_cabo(self):
        r = self.post_update(login(self.admin), self.coord1, role="CABO", parent=str(self.coord2.pk))
        self.assertEqual(r.status_code, 200)
        self.assertIn("role", r.context["edit_form"].errors)
        self.coord1.refresh_from_db()
        self.assertEqual(self.coord1.role, Role.COORDENADOR)
        # sem cabos, pode
        r = self.post_update(login(self.admin), self.coord2, role="CABO", parent=str(self.coord1.pk))
        self.assertEqual(r.status_code, 200)  # coord2 tem o cabo2
        self.cabo2.delete()
        r = self.post_update(login(self.admin), self.coord2, role="CABO", parent=str(self.coord1.pk))
        self.assertEqual(r.status_code, 302)
        self.coord2.refresh_from_db()
        self.assertEqual((self.coord2.role, self.coord2.parent_id), (Role.CABO, self.coord1.pk))

    def test_admin_cannot_change_own_role_or_use_foreign_parent(self):
        c = login(self.admin)
        r = self.post_update(c, self.admin, role="CABO", parent=str(self.coord1.pk))
        self.assertEqual(r.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Role.ADMIN)
        r = self.post_update(c, self.cabo1, parent=str(self.coord_b.pk))
        self.assertEqual(r.status_code, 200)
        self.assertIn("parent", r.context["edit_form"].errors)
        self.cabo1.refresh_from_db()
        self.assertEqual(self.cabo1.parent_id, self.coord1.pk)

    def test_no_change_is_reported(self):
        r = self.post_update(login(self.admin), self.cabo2, name="Cabo Dois", email="cabo2@a.com", role="CABO", parent=str(self.coord2.pk))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self.audit("user.update").exists())

    def test_edit_requires_permission(self):
        self.grant(Role.COORDENADOR, "equipe", can_edit=False)
        r = self.post_update(login(self.coord1), self.cabo1, name="Sem permissão")
        self.assertEqual(r.status_code, 403)


class ActivationTests(BaseTeamTest):
    def test_admin_deactivates_and_reactivates(self):
        session = login(self.cabo1)
        self.assertEqual(session.get("/painel/perfil/").status_code, 200)
        c = login(self.admin)
        r = c.post(reverse("team:deactivate", args=[self.cabo1.pk]))
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertFalse(self.cabo1.is_active)
        self.assertTrue(self.audit("user.deactivate").exists())
        # a sessão aberta e o login deixam de funcionar
        self.assertEqual(session.get("/painel/perfil/").status_code, 302)
        self.assertFalse(Client().login(username="cabo1@a.com", password=PASSWORD))
        r = c.post(reverse("team:activate", args=[self.cabo1.pk]))
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertTrue(self.cabo1.is_active)
        self.assertTrue(self.audit("user.activate").exists())
        self.assertTrue(Client().login(username="cabo1@a.com", password=PASSWORD))

    def test_cannot_deactivate_yourself(self):
        r = login(self.admin).post(reverse("team:deactivate", args=[self.admin.pk]), follow=True)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertContains(r, "próprio acesso")

    def test_coordinator_manages_only_his_cabos(self):
        c = login(self.coord1)
        self.assertEqual(c.post(reverse("team:deactivate", args=[self.cabo1.pk])).status_code, 302)
        self.assertEqual(c.post(reverse("team:deactivate", args=[self.cabo2.pk])).status_code, 404)
        self.assertEqual(c.post(reverse("team:deactivate", args=[self.coord1.pk])).status_code, 403)
        self.assertEqual(c.post(reverse("team:deactivate", args=[self.admin.pk])).status_code, 404)
        self.cabo2.refresh_from_db()
        self.assertTrue(self.cabo2.is_active)

    def test_inactive_member_public_link_owner_is_flagged_inactive(self):
        login(self.admin).post(reverse("team:deactivate", args=[self.cabo1.pk]))
        r = login(self.admin).get(reverse("team:detail", args=[self.cabo1.pk]))
        self.assertContains(r, "desativado")
        self.assertNotContains(r, "data:image/png;base64,")

    def test_last_active_admin_is_protected_in_service(self):
        request = RequestFactory().post("/")
        request.user = self.coord1  # ator qualquer (o admin é o único ativo)
        with self.assertRaises(TeamError) as ctx:
            services.set_member_active(request, self.admin, False)
        self.assertIn("último administrador", ctx.exception.message)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_other_admin_can_be_deactivated_when_not_the_last(self):
        admin2 = make_user(self.camp, "admin2@a.com", Role.ADMIN)
        r = login(self.admin).post(reverse("team:deactivate", args=[admin2.pk]))
        self.assertEqual(r.status_code, 302)
        admin2.refresh_from_db()
        self.assertFalse(admin2.is_active)


class PasswordAndLinkTests(BaseTeamTest):
    def test_reset_password_shows_new_one_once_and_kills_other_sessions(self):
        other_session = login(self.cabo1)
        self.assertEqual(other_session.get("/painel/perfil/").status_code, 200)
        r = login(self.admin).post(reverse("team:reset_password", args=[self.cabo1.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "team/credentials.html")
        password = r.context["password"]
        self.cabo1.refresh_from_db()
        self.assertTrue(self.cabo1.check_password(password))
        self.assertFalse(self.cabo1.check_password(PASSWORD))
        self.assertIn("no-store", r["Cache-Control"])
        self.assertEqual(other_session.get("/painel/perfil/").status_code, 302)  # sessão antiga encerrada
        self.assertTrue(Client().login(username="cabo1@a.com", password=password))
        log = self.audit("user.password_reset").get()
        self.assertNotIn(password, str(log.details))

    def test_cannot_reset_own_password_here(self):
        r = login(self.admin).post(reverse("team:reset_password", args=[self.admin.pk]), follow=True)
        self.assertContains(r, "Meu perfil")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(PASSWORD))

    def test_coordinator_resets_only_his_cabo(self):
        c = login(self.coord1)
        self.assertEqual(c.post(reverse("team:reset_password", args=[self.cabo1.pk])).status_code, 200)
        self.assertEqual(c.post(reverse("team:reset_password", args=[self.cabo2.pk])).status_code, 404)
        self.cabo2.refresh_from_db()
        self.assertTrue(self.cabo2.check_password(PASSWORD))

    def test_regenerate_link_invalidates_the_old_code(self):
        old = self.cabo1.invite_code
        r = login(self.admin).post(reverse("team:regenerate_link", args=[self.cabo1.pk]))
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertNotEqual(self.cabo1.invite_code, old)
        self.assertFalse(User.objects.filter(invite_code=old).exists())
        self.assertTrue(self.audit("user.invite_regenerate").exists())

    def test_regenerate_link_scope(self):
        c = login(self.coord1)
        self.assertEqual(c.post(reverse("team:regenerate_link", args=[self.cabo1.pk])).status_code, 302)
        self.assertEqual(c.post(reverse("team:regenerate_link", args=[self.coord1.pk])).status_code, 302)  # o próprio link
        self.assertEqual(c.post(reverse("team:regenerate_link", args=[self.cabo2.pk])).status_code, 404)
        self.assertEqual(c.post(reverse("team:regenerate_link", args=[self.cabo_b.pk])).status_code, 404)
        self.assertEqual(login(self.cabo1).post(reverse("team:regenerate_link", args=[self.cabo1.pk])).status_code, 403)


class MoveTests(BaseTeamTest):
    def move(self, client, member, parent):
        return client.post(reverse("team:move", args=[member.pk]), {"parent": str(parent.pk)})

    def test_admin_moves_cabo_to_another_coordinator(self):
        r = self.move(login(self.admin), self.cabo1, self.coord2)
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertEqual(self.cabo1.parent_id, self.coord2.pk)
        self.assertTrue(self.audit("user.update").filter(details__moved=True).exists())

    def test_invalid_targets(self):
        c = login(self.admin)
        for target in (self.admin, self.cabo2, self.coord_b, self.admin_b):
            self.move(c, self.cabo1, target)
            self.cabo1.refresh_from_db()
            self.assertEqual(self.cabo1.parent_id, self.coord1.pk, target.email)
        self.coord2.is_active = False
        self.coord2.save()
        self.move(c, self.cabo1, self.coord2)
        self.cabo1.refresh_from_db()
        self.assertEqual(self.cabo1.parent_id, self.coord1.pk)

    def test_malformed_parent_does_not_crash(self):
        r = login(self.admin).post(reverse("team:move", args=[self.cabo1.pk]), {"parent": "xx"})
        self.assertEqual(r.status_code, 302)
        r = login(self.admin).post(reverse("team:move", args=[self.cabo1.pk]), {})
        self.assertEqual(r.status_code, 302)

    def test_coordinator_cannot_move_and_admin_cannot_be_moved(self):
        self.move(login(self.coord1), self.cabo1, self.coord2)
        self.cabo1.refresh_from_db()
        self.assertEqual(self.cabo1.parent_id, self.coord1.pk)
        self.move(login(self.admin), self.admin, self.coord1)
        self.admin.refresh_from_db()
        self.assertIsNone(self.admin.parent_id)


class DeleteTests(BaseTeamTest):
    def post_delete(self, client, member, **data):
        return client.post(reverse("team:delete", args=[member.pk]), {k: str(v) for k, v in data.items()})

    def test_member_without_dependencies_is_deleted(self):
        r = self.post_delete(login(self.admin), self.cabo1)
        self.assertRedirects(r, reverse("team:list"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.cabo1.pk).exists())
        log = self.audit("user.delete").get()
        self.assertEqual(log.entity_id, str(self.cabo1.pk))
        self.assertNotIn("Cabo Um", str(log.details))

    def test_voters_must_be_transferred(self):
        v = make_voter(self.camp, self.cabo1, 1)
        make_voter(self.camp, self.cabo1, 2)
        c = login(self.admin)
        r = self.post_delete(c, self.cabo1)
        self.assertEqual(r.status_code, 200)
        self.assertIn("transfer_to", r.context["delete_form"].errors)
        self.assertTrue(r.context["delete_open"])
        self.assertTrue(User.objects.filter(pk=self.cabo1.pk).exists())
        r = self.post_delete(c, self.cabo1, transfer_to=self.cabo2.pk)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.cabo1.pk).exists())
        v.refresh_from_db()
        self.assertEqual(v.registered_by_id, self.cabo2.pk)
        self.assertEqual(Voter.objects.filter(registered_by=self.cabo2).count(), 2)
        self.assertEqual(self.audit("user.delete").get().details["voters_transferred"], 2)

    def test_transfer_target_is_validated(self):
        make_voter(self.camp, self.cabo1, 1)
        c = login(self.admin)
        inactive = make_user(self.camp, "off@a.com", Role.CABO, parent=self.coord1, is_active=False)
        for bad in (self.cabo1.pk, self.cabo_b.pk, self.admin_b.pk, inactive.pk, "xx", "00000000-0000-0000-0000-000000000000"):
            r = self.post_delete(c, self.cabo1, transfer_to=bad)
            self.assertEqual(r.status_code, 200, bad)
            self.assertTrue(r.context["delete_form"].errors, bad)
        self.assertTrue(User.objects.filter(pk=self.cabo1.pk).exists())
        self.assertEqual(Voter.objects.filter(registered_by=self.cabo1).count(), 1)

    def test_nothing_is_lost_on_foreign_voters(self):
        make_voter(self.other, self.cabo_b, 9)
        self.post_delete(login(self.admin), self.cabo1)
        self.assertEqual(Voter.objects.filter(registered_by=self.cabo_b).count(), 1)

    def test_coordinator_delete_needs_permission_and_stays_in_scope(self):
        make_voter(self.camp, self.cabo1, 1)
        c = login(self.coord1)
        self.assertEqual(self.post_delete(c, self.cabo1, transfer_to=self.coord1.pk).status_code, 403)
        self.grant(Role.COORDENADOR, "equipe", can_delete=True)
        self.assertEqual(self.post_delete(c, self.cabo2).status_code, 404)  # fora da rede
        r = self.post_delete(c, self.cabo1, transfer_to=self.cabo2.pk)  # destino fora da rede dele
        self.assertEqual(r.status_code, 200)
        self.assertIn("transfer_to", r.context["delete_form"].errors)
        r = self.post_delete(c, self.cabo1, transfer_to=self.coord1.pk)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Voter.objects.filter(registered_by=self.coord1).count(), 1)
        self.assertEqual(self.post_delete(c, self.coord1).status_code, 403)  # nunca a si mesmo

    def test_children_need_a_new_parent(self):
        c = login(self.admin)
        r = self.post_delete(c, self.coord1)
        self.assertEqual(r.status_code, 200)
        self.assertIn("new_parent", r.context["delete_form"].errors)
        # admin não pode herdar cabos enquanto houver outro coordenador ativo
        r = self.post_delete(c, self.coord1, new_parent=self.admin.pk)
        self.assertEqual(r.status_code, 200)
        # cabo não é responsável; outra campanha também não
        for bad in (self.cabo2.pk, self.coord_b.pk, self.coord1.pk):
            self.assertEqual(self.post_delete(c, self.coord1, new_parent=bad).status_code, 200, bad)
        self.assertTrue(User.objects.filter(pk=self.coord1.pk).exists())
        r = self.post_delete(c, self.coord1, new_parent=self.coord2.pk)
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertEqual(self.cabo1.parent_id, self.coord2.pk)
        self.assertEqual(self.audit("user.delete").get().details["children_moved"], 1)

    def test_children_go_to_admin_when_no_other_coordinator(self):
        self.cabo2.delete()
        self.coord2.delete()
        r = self.post_delete(login(self.admin), self.coord1, new_parent=self.admin.pk)
        self.assertEqual(r.status_code, 302)
        self.cabo1.refresh_from_db()
        self.assertEqual(self.cabo1.parent_id, self.admin.pk)

    def test_voters_and_children_together_in_one_transaction(self):
        make_voter(self.camp, self.coord1, 1)
        make_voter(self.camp, self.cabo1, 2)
        c = login(self.admin)
        r = self.post_delete(c, self.coord1, transfer_to=self.cabo2.pk)
        self.assertEqual(r.status_code, 200)  # falta o novo responsável: nada muda
        self.assertEqual(Voter.objects.filter(registered_by=self.coord1).count(), 1)
        r = self.post_delete(c, self.coord1, transfer_to=self.cabo2.pk, new_parent=self.coord2.pk)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Voter.objects.filter(registered_by=self.cabo2).count(), 1)
        self.assertFalse(User.objects.filter(pk=self.coord1.pk).exists())

    def test_cannot_delete_yourself_or_other_campaign(self):
        c = login(self.admin)
        r = self.post_delete(c, self.admin)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertEqual(self.post_delete(c, self.admin_b).status_code, 404)
        self.assertEqual(self.post_delete(c, self.cabo_b).status_code, 404)
        self.assertTrue(User.objects.filter(pk=self.cabo_b.pk).exists())

    def test_last_admin_is_protected_in_service(self):
        request = RequestFactory().post("/")
        request.user = self.coord1
        form_data = {"transfer_to_obj": None, "new_parent_obj": None}
        with self.assertRaises(TeamError) as ctx:
            services.delete_member(request, self.admin, form_data)
        self.assertIn("último administrador", ctx.exception.message)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_service_refuses_when_voters_remain(self):
        make_voter(self.camp, self.cabo1, 1)
        request = RequestFactory().post("/")
        request.user = self.admin
        with self.assertRaises(TeamError):
            services.delete_member(request, self.cabo1, {"transfer_to_obj": None, "new_parent_obj": None})
        self.assertTrue(User.objects.filter(pk=self.cabo1.pk).exists())
        self.assertEqual(Voter.objects.filter(registered_by=self.cabo1).count(), 1)

    def test_other_admin_can_be_deleted_when_not_last(self):
        admin2 = make_user(self.camp, "admin2@a.com", Role.ADMIN)
        make_voter(self.camp, admin2, 1)
        c = login(self.admin)
        r = self.post_delete(c, admin2, transfer_to=self.admin.pk)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=admin2.pk).exists())
        self.assertEqual(Voter.objects.filter(registered_by=self.admin).count(), 1)

