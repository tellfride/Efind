"""Recuperação de senha por e-mail: fluxo completo, anti-enumeração, limites e segurança do link."""

import re
from unittest import mock

from django.contrib.auth.forms import PasswordResetForm
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from apps.accounts.models import User
from apps.auditlog.models import AuditLog
from apps.core.constants import Role
from apps.core.tests.test_access import PASSWORD, make_campaign, make_user

LINK_RE = re.compile(r"https?://\S+/senha/redefinir/\S+/")


@override_settings(APP_URL="https://efind.example", PASSWORD_RESET_ENABLED=True)
class PasswordResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("alfa")
        cls.admin = make_user(cls.campaign, "admin@a.com", Role.ADMIN)
        cls.cabo = make_user(cls.campaign, "cabo@a.com", Role.CABO, parent=cls.admin)
        cls.flagged = make_user(cls.campaign, "novo@a.com", Role.CABO, parent=cls.admin, must_change_password=True)
        cls.inactive = make_user(cls.campaign, "off@a.com", Role.CABO, parent=cls.admin)
        User.objects.filter(pk=cls.inactive.pk).update(is_active=False)

    def setUp(self):
        cache.clear()  # os limites de taxa usam o cache local

    def request_reset(self, email, **extra):
        return Client().post("/senha/esqueci/", {"email": email}, **extra)

    def test_pages_render(self):
        self.assertContains(Client().get("/senha/esqueci/"), "Esqueci minha senha")
        self.assertContains(Client().get("/senha/esqueci/enviado/"), "Verifique seu e-mail")
        self.assertContains(Client().get("/senha/redefinir/concluido/"), "Senha alterada")
        self.assertContains(Client().get("/login/"), "/senha/esqueci/")

    def test_known_and_unknown_emails_get_the_same_response(self):
        known = self.request_reset("cabo@a.com")
        unknown = self.request_reset("ninguem@a.com")
        self.assertRedirects(known, "/senha/esqueci/enviado/", fetch_redirect_response=False)
        self.assertRedirects(unknown, "/senha/esqueci/enviado/", fetch_redirect_response=False)
        self.assertEqual([m.to for m in mail.outbox], [["cabo@a.com"]])  # só a conta existente recebe

    def test_inactive_accounts_get_no_email(self):
        self.request_reset("off@a.com")
        self.assertEqual(mail.outbox, [])

    def test_email_matching_is_case_insensitive(self):
        self.request_reset("CABO@A.COM")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(ALLOWED_HOSTS=["evil.example", "testserver"])  # sem isso o Django já recusa o Host (400)
    def test_link_uses_app_url_not_the_host_header(self):
        self.request_reset("cabo@a.com", HTTP_HOST="evil.example")
        body = mail.outbox[0].body
        self.assertIn("https://efind.example/senha/redefinir/", body)
        self.assertNotIn("evil.example", body)
        self.assertIn("60 minutos", body)
        self.assertEqual(mail.outbox[0].subject, "Redefinição de senha — E-Find")

    def test_rate_limit_per_email_still_looks_the_same(self):
        for _ in range(6):
            response = self.request_reset("cabo@a.com")
            self.assertRedirects(response, "/senha/esqueci/enviado/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 3)  # 3 por hora; o resto é descartado em silêncio

    def test_smtp_failure_does_not_break_or_leak(self):
        with mock.patch.object(PasswordResetForm, "send_mail", side_effect=OSError("smtp down")):
            with self.assertLogs("apps.accounts.password_reset", level="ERROR") as logs:
                response = self.request_reset("cabo@a.com")
        self.assertRedirects(response, "/senha/esqueci/enviado/", fetch_redirect_response=False)
        self.assertNotIn("cabo@a.com", " ".join(logs.output))  # o log não carrega o e-mail do usuário

    def test_full_flow_changes_password_clears_flag_and_invalidates_link(self):
        self.request_reset("novo@a.com")
        link = LINK_RE.search(mail.outbox[0].body).group(0)
        path = "/" + link.split("efind.example/", 1)[1]

        client = Client()
        step = client.get(path)  # o Django troca o token por um "set-password" guardado na sessão
        self.assertEqual(step.status_code, 302)
        form_url = step["Location"]
        self.assertContains(client.get(form_url), "Crie uma nova senha")

        # senha fraca (só números) é recusada e o link continua valendo
        weak = client.post(form_url, {"new_password1": "12345678", "new_password2": "12345678"})
        self.assertEqual(weak.status_code, 200)
        self.assertContains(weak, "letras e números")
        mismatch = client.post(form_url, {"new_password1": "NovaSenha123", "new_password2": "OutraSenha123"})
        self.assertEqual(mismatch.status_code, 200)

        done = client.post(form_url, {"new_password1": "NovaSenha123", "new_password2": "NovaSenha123"})
        self.assertRedirects(done, "/senha/redefinir/concluido/", fetch_redirect_response=False)

        self.flagged.refresh_from_db()
        self.assertTrue(self.flagged.check_password("NovaSenha123"))
        self.assertFalse(self.flagged.must_change_password)  # a senha provisória deixou de valer
        self.assertTrue(Client().login(username="novo@a.com", password="NovaSenha123"))
        self.assertFalse(Client().login(username="novo@a.com", password=PASSWORD))
        self.assertTrue(AuditLog.objects.filter(action="auth.password_reset_email", user=self.flagged).exists())

        reused = Client().get(path, follow=True)  # link de uso único
        self.assertContains(reused, "Link inválido ou expirado")

    def test_open_sessions_are_ended_after_a_reset(self):
        logged = Client()
        self.assertTrue(logged.login(username="cabo@a.com", password=PASSWORD))
        self.assertEqual(logged.get("/painel/perfil/").status_code, 200)
        self.request_reset("cabo@a.com")
        path = "/" + LINK_RE.search(mail.outbox[0].body).group(0).split("efind.example/", 1)[1]
        client = Client()
        form_url = client.get(path)["Location"]
        client.post(form_url, {"new_password1": "NovaSenha123", "new_password2": "NovaSenha123"})
        self.assertEqual(logged.get("/painel/perfil/").status_code, 302)  # a sessão antiga caiu

    def test_tampered_token_is_rejected(self):
        self.request_reset("cabo@a.com")
        path = "/" + LINK_RE.search(mail.outbox[0].body).group(0).split("efind.example/", 1)[1]
        tampered = path[:-2] + ("a/" if not path[:-1].endswith("a") else "b/")
        self.assertContains(Client().get(tampered, follow=True), "Link inválido ou expirado")
        self.assertContains(Client().get("/senha/redefinir/xxxx/yyyy-zzz/", follow=True), "Link inválido ou expirado")


class PasswordResetDisabledTests(TestCase):
    @override_settings(PASSWORD_RESET_ENABLED=False)
    def test_returns_404_and_hides_the_login_link(self):
        client = Client()
        self.assertEqual(client.get("/senha/esqueci/").status_code, 404)
        self.assertEqual(client.post("/senha/esqueci/", {"email": "x@y.com"}).status_code, 404)
        self.assertEqual(client.get("/senha/redefinir/abc/def/").status_code, 404)
        self.assertNotContains(client.get("/login/"), "Esqueci minha senha")
        self.assertEqual(mail.outbox, [])
