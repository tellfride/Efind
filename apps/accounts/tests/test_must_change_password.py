"""Senha provisória: quem entra com a senha definida por um administrador precisa trocá-la antes de usar o sistema."""

from types import SimpleNamespace

from django.test import Client, RequestFactory, TestCase

from apps.accounts.models import User
from apps.core.constants import Role
from apps.core.tests.test_access import PASSWORD, make_campaign, make_user
from apps.superadmin.services import create_account, reset_password
from apps.team.services import create_member


def login(email, password=PASSWORD):
    client = Client()
    assert client.login(username=email, password=password)
    return client


class MustChangePasswordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("alfa")
        cls.admin = make_user(cls.campaign, "admin@a.com", Role.ADMIN)
        cls.coord = make_user(cls.campaign, "coord@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.cabo = make_user(cls.campaign, "cabo@a.com", Role.CABO, parent=cls.coord)
        cls.flagged = make_user(cls.campaign, "novo@a.com", Role.CABO, parent=cls.coord, must_change_password=True)
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD)
        cls.flagged_super = User.objects.create_superuser("super2@x.com", PASSWORD, must_change_password=True)

    def test_flagged_user_is_sent_to_the_password_page(self):
        client = login("novo@a.com")
        for path in ("/painel/", "/painel/apoiadores/", "/painel/meu-link/"):
            response = client.get(path)
            self.assertRedirects(response, "/painel/perfil/", fetch_redirect_response=False, msg_prefix=path)
        page = client.get("/painel/perfil/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Defina uma nova senha")

    def test_flagged_user_cannot_use_api_endpoints(self):
        response = login("novo@a.com").get("/api/painel/mapa/dados/")
        self.assertEqual(response.status_code, 403)
        self.assertIn("nova senha", response.json()["error"])

    def test_logout_and_static_stay_reachable(self):
        client = login("novo@a.com")
        self.assertEqual(client.get("/favicon.ico").status_code, 302)  # redireciona ao SVG, não ao perfil
        self.assertEqual(client.post("/logout/").status_code, 302)
        self.assertNotEqual(client.get("/painel/").status_code, 200)

    def test_changing_the_password_clears_the_flag_and_unlocks_the_system(self):
        client = login("novo@a.com")
        response = client.post(
            "/painel/perfil/",
            {"action": "password", "current_password": PASSWORD, "new_password": "NovaSenha123", "confirm_password": "NovaSenha123"},
        )
        self.assertEqual(response.status_code, 302)
        self.flagged.refresh_from_db()
        self.assertFalse(self.flagged.must_change_password)
        self.assertEqual(client.get("/painel/").status_code, 200)

    def test_a_wrong_new_password_keeps_the_lock(self):
        client = login("novo@a.com")
        client.post(
            "/painel/perfil/",
            {"action": "password", "current_password": PASSWORD, "new_password": "12345678", "confirm_password": "12345678"},
        )
        self.flagged.refresh_from_db()
        self.assertTrue(self.flagged.must_change_password)
        self.assertRedirects(client.get("/painel/"), "/painel/perfil/", fetch_redirect_response=False)

    def test_super_admin_variant(self):
        client = login("super2@x.com")
        self.assertRedirects(client.get("/super/"), "/super/perfil/", fetch_redirect_response=False)
        self.assertEqual(client.get("/super/perfil/").status_code, 200)

    def test_regular_users_are_not_affected(self):
        self.assertEqual(login("cabo@a.com").get("/painel/").status_code, 200)
        self.assertEqual(login("super@x.com").get("/super/").status_code, 200)

    def test_admin_password_reset_flags_the_member(self):
        client = login("admin@a.com")
        response = client.post(f"/painel/equipe/{self.cabo.pk}/redefinir-senha/")
        self.assertIn(response.status_code, (200, 302))
        self.cabo.refresh_from_db()
        self.assertTrue(self.cabo.must_change_password)

    def test_creating_a_member_flags_the_account(self):
        request = RequestFactory().post("/")
        request.user = self.admin
        member, _password = create_member(
            request,
            {"email": "criado@a.com", "name": "Criado", "placement": SimpleNamespace(role=Role.CABO, parent_id=self.coord.pk)},
        )
        self.assertTrue(member.must_change_password)

    def test_super_admin_services_flag_accounts(self):
        request = RequestFactory().post("/")
        request.user = self.superuser
        user, _creds = create_account(
            request, role=Role.ADMIN, campaign=self.campaign, data={"email": "novoadm@a.com", "name": "Novo Adm", "password": ""}
        )
        self.assertTrue(user.must_change_password)
        User.objects.filter(pk=user.pk).update(must_change_password=False)
        user.refresh_from_db()
        reset_password(request, user, campaign=self.campaign)
        user.refresh_from_db()
        self.assertTrue(user.must_change_password)
