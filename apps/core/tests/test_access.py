"""Isolamento entre campanhas e escopo hierárquico (a parte mais crítica da segurança)."""

from django.test import Client, TestCase

from apps.accounts.models import RolePermission, User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.access import (
    can_access_member,
    get_member_in_scope,
    get_voter_in_scope,
    team_scope,
    voter_scope,
    voters_queryset,
)
from apps.core.constants import Role
from apps.voters.models import Voter

PASSWORD = "Senha@12345"


def make_campaign(slug):
    campaign = Campaign.objects.create(
        slug=slug, candidate_name=slug.title(), ballot_name=slug.title(), office="VEREADOR", election_year=2026
    )
    bootstrap_campaign(campaign)
    return campaign


def make_user(campaign, email, role, parent=None, **extra):
    return User.objects.create_user(email, PASSWORD, name=email.split("@")[0], role=role, campaign=campaign, parent=parent, **extra)


def make_voter(campaign, registered_by, n, **extra):
    return Voter.objects.create(campaign=campaign, registered_by=registered_by, name=f"Apoiador {n}", phone=f"5511900000{n:03d}", **extra)


class ScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.b = make_campaign("beta")
        cls.admin_a = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.coord1 = make_user(cls.a, "coord1@a.com", Role.COORDENADOR, parent=cls.admin_a)
        cls.coord2 = make_user(cls.a, "coord2@a.com", Role.COORDENADOR, parent=cls.admin_a)
        cls.cabo1 = make_user(cls.a, "cabo1@a.com", Role.CABO, parent=cls.coord1)
        cls.cabo2 = make_user(cls.a, "cabo2@a.com", Role.CABO, parent=cls.coord2)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.v_cabo1 = make_voter(cls.a, cls.cabo1, 1, neighborhood="Centro")
        cls.v_cabo2 = make_voter(cls.a, cls.cabo2, 2, neighborhood="Centro")
        cls.v_coord1 = make_voter(cls.a, cls.coord1, 3, neighborhood="Cambuí")
        cls.v_b = make_voter(cls.b, cls.admin_b, 4, neighborhood="Centro")

    def ids(self, qs):
        return {v.pk for v in qs}

    def test_admin_sees_only_own_campaign(self):
        self.assertEqual(self.ids(voter_scope(self.admin_a)), {self.v_cabo1.pk, self.v_cabo2.pk, self.v_coord1.pk})
        self.assertEqual(self.ids(voter_scope(self.admin_b)), {self.v_b.pk})

    def test_coordinator_sees_self_and_direct_cabos(self):
        self.assertEqual(self.ids(voter_scope(self.coord1)), {self.v_cabo1.pk, self.v_coord1.pk})
        self.assertEqual(self.ids(voter_scope(self.coord2)), {self.v_cabo2.pk})

    def test_cabo_sees_only_own(self):
        self.assertEqual(self.ids(voter_scope(self.cabo1)), {self.v_cabo1.pk})

    def test_filters_never_widen_scope(self):
        # cabo1 filtra pelo cabo2 → nada (o filtro é AND com o escopo)
        qs = voters_queryset(self.cabo1, {"registered_by_ids": [str(self.cabo2.pk)]})
        self.assertEqual(qs.count(), 0)
        qs = voters_queryset(self.cabo1, {"neighborhoods": ["Centro"]})
        self.assertEqual(self.ids(qs), {self.v_cabo1.pk})

    def test_coordinator_filter_expands_to_his_cabos_only(self):
        qs = voters_queryset(self.admin_a, {"coordinator_ids": [str(self.coord1.pk)]})
        self.assertEqual(self.ids(qs), {self.v_cabo1.pk, self.v_coord1.pk})

    def test_lookup_by_id_respects_scope(self):
        self.assertIsNone(get_voter_in_scope(self.cabo1, self.v_cabo2.pk))
        self.assertIsNone(get_voter_in_scope(self.admin_a, self.v_b.pk))  # outra campanha
        self.assertIsNone(get_voter_in_scope(self.admin_a, "id-malformado"))
        self.assertEqual(get_voter_in_scope(self.coord1, self.v_cabo1.pk), self.v_cabo1)

    def test_team_scope(self):
        self.assertEqual(self.ids(team_scope(self.coord1)), {self.coord1.pk, self.cabo1.pk})
        self.assertEqual(self.ids(team_scope(self.cabo1)), {self.cabo1.pk})
        self.assertEqual(len(team_scope(self.admin_a)), 5)
        self.assertTrue(can_access_member(self.coord1, self.cabo1.pk))
        self.assertFalse(can_access_member(self.coord1, self.cabo2.pk))
        self.assertIsNone(get_member_in_scope(self.admin_a, self.admin_b.pk))

    def test_super_admin_sees_no_voters(self):
        superuser = User.objects.create_superuser("super@x.com", PASSWORD)
        self.assertEqual(voter_scope(superuser).count(), 0)
        self.assertEqual(team_scope(superuser).count(), 0)

    def test_voter_phone_unique_per_campaign_only(self):
        # mesmo telefone em outra campanha é permitido
        Voter.objects.create(campaign=self.b, registered_by=self.admin_b, name="X", phone=self.v_cabo1.phone)
        with self.assertRaises(Exception):
            Voter.objects.create(campaign=self.a, registered_by=self.cabo1, name="Y", phone=self.v_cabo1.phone)


class AuthFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("alfa")
        cls.admin = make_user(cls.campaign, "admin@a.com", Role.ADMIN)
        cls.coord = make_user(cls.campaign, "coord@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.cabo = make_user(cls.campaign, "cabo@a.com", Role.CABO, parent=cls.coord)
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD)

    def login(self, email, password=PASSWORD):
        client = Client()
        response = client.post("/login/", {"email": email, "password": password})
        return client, response

    def test_login_redirects_by_role(self):
        _, r = self.login("admin@a.com")
        self.assertRedirects(r, "/painel/", fetch_redirect_response=False)
        _, r = self.login("super@x.com")
        self.assertRedirects(r, "/super/", fetch_redirect_response=False)

    def test_login_is_case_insensitive_and_rejects_bad_password(self):
        _, r = self.login("ADMIN@A.COM")
        self.assertEqual(r.status_code, 302)
        _, r = self.login("admin@a.com", "errada")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "E-mail ou senha incorretos")

    def test_open_redirect_is_blocked(self):
        client = Client()
        r = client.post("/login/", {"email": "admin@a.com", "password": PASSWORD, "next": "https://evil.example/x"})
        self.assertRedirects(r, "/painel/", fetch_redirect_response=False)

    def test_anonymous_is_sent_to_login(self):
        r = Client().get("/painel/apoiadores/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/login/?next="))

    def test_super_admin_cannot_open_campaign_panel_and_vice_versa(self):
        client, _ = self.login("super@x.com")
        self.assertEqual(client.get("/painel/apoiadores/").status_code, 302)
        client, _ = self.login("admin@a.com")
        self.assertEqual(client.get("/super/campanhas/").status_code, 302)

    def test_cabo_cannot_open_modules_without_permission(self):
        client, _ = self.login("cabo@a.com")
        self.assertEqual(client.get("/painel/apoiadores/").status_code, 200)
        self.assertEqual(client.get("/painel/equipe/").status_code, 403)
        self.assertEqual(client.get("/painel/permissoes/").status_code, 403)
        self.assertEqual(client.get("/painel/mensagens/disparos/").status_code, 403)

    def test_admin_changes_to_permission_matrix_take_effect_immediately(self):
        client, _ = self.login("cabo@a.com")
        self.assertEqual(client.get("/painel/mapa/").status_code, 200)
        RolePermission.objects.filter(campaign=self.campaign, role=Role.CABO, module="mapa").update(can_view=False)
        self.assertEqual(client.get("/painel/mapa/").status_code, 403)

    def test_deactivated_user_loses_access(self):
        client, _ = self.login("cabo@a.com")
        self.assertEqual(client.get("/painel/apoiadores/").status_code, 200)
        User.objects.filter(pk=self.cabo.pk).update(is_active=False)
        self.assertEqual(client.get("/painel/apoiadores/").status_code, 302)

    def test_suspended_campaign_blocks_login_and_active_sessions(self):
        client, _ = self.login("admin@a.com")
        Campaign.objects.filter(pk=self.campaign.pk).update(status="SUSPENDED")
        self.assertEqual(client.get("/painel/").status_code, 302)
        _, r = self.login("coord@a.com")
        self.assertContains(r, "suspensa")

    def test_logout_requires_post(self):
        client, _ = self.login("admin@a.com")
        self.assertEqual(client.get("/logout/").status_code, 405)
        self.assertEqual(client.post("/logout/").status_code, 302)
        self.assertEqual(client.get("/painel/").status_code, 302)

    def test_password_change_keeps_current_session_and_ends_others(self):
        client, _ = self.login("coord@a.com")
        other, _ = self.login("coord@a.com")
        r = client.post(
            "/painel/perfil/",
            {"action": "password", "current_password": PASSWORD, "new_password": "NovaSenha123", "confirm_password": "NovaSenha123"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(client.get("/painel/perfil/").status_code, 200)
        self.assertEqual(other.get("/painel/perfil/").status_code, 302)
