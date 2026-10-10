"""Telas e ações de /painel/whatsapp/: permissões, isolamento entre campanhas, assistente, edição, segredos e auditoria."""

from __future__ import annotations

import json
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.auditlog.models import AuditLog
from apps.core.constants import BroadcastStatus, ConnectionStatus, Role
from apps.core.crypto import decrypt_json, mask_secret
from apps.messaging.models import Broadcast
from apps.whatsapp.models import WhatsAppConnection
from apps.whatsapp.providers import common
from apps.whatsapp.registry import PROVIDERS

from .helpers import (
    D360_KEY,
    META_APP_SECRET,
    META_CREDENTIALS,
    META_TOKEN,
    TWILIO_AUTH,
    crypto_settings,
    grant,
    make_campaign,
    make_connection,
    make_super_admin,
    make_user,
)

ALL_SECRETS = (META_TOKEN, META_APP_SECRET, TWILIO_AUTH, D360_KEY)

META_OK = common.HttpResult(
    200, True, {"display_phone_number": "+55 11 98765-4321", "verified_name": "Campanha", "quality_rating": "GREEN"}
)
META_AUTH_ERROR = common.HttpResult(401, False, {"error": {"message": "Invalid OAuth access token", "code": 190}})
META_SENT = common.HttpResult(200, True, {"messages": [{"id": "wamid.TESTE"}]})


def meta_form(**overrides):
    data = {
        "provider": "META_CLOUD",
        "name": "WhatsApp oficial",
        "phone_number": "",
        "rate_per_minute": "20",
        "cred_phone_number_id": "123456789012345",
        "cred_business_account_id": "",
        "cred_access_token": META_TOKEN,
        "cred_app_secret": META_APP_SECRET,
        "cred_api_version": "v21.0",
    }
    data.update(overrides)
    return data


@crypto_settings
class WhatsAppViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.b = make_campaign("beta")
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.coord = make_user(cls.a, "coord@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.cabo = make_user(cls.a, "cabo@a.com", Role.CABO, parent=cls.coord)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.super_admin = make_super_admin()

    def setUp(self):
        super().setUp()
        cache.clear()  # limites de uso (rate_limit) ficam no cache e os usuários são compartilhados na classe

    def login(self, user):
        self.client.force_login(user)
        return self.client

    def url(self, name, conn=None):
        return reverse(f"whatsapp:{name}", args=[conn.pk] if conn is not None else [])


# ------------------------------------------------------------------------------------------------ Acesso


class AccessTests(WhatsAppViewTestCase):
    def setUp(self):
        super().setUp()
        self.conn = make_connection(self.a)
        self.get_urls = [
            reverse("whatsapp:connections"),
            reverse("whatsapp:connection_new"),
            self.url("connection_edit", self.conn),
            self.url("connection_webhook", self.conn),
            self.url("connection_check", self.conn),
        ]
        self.post_urls = [
            self.url(name, self.conn)
            for name in ("connection_test", "connection_default", "connection_disable", "connection_enable", "connection_delete")
        ]
        self.api_urls = [
            self.url(name, self.conn) for name in ("api_test_connection", "api_send_test_message", "api_register_webhook")
        ]

    def test_anonymous_is_redirected_to_login(self):
        for url in self.get_urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302, url)
            self.assertTrue(res["Location"].startswith("/login/"), url)
        for url in self.post_urls:
            res = self.client.post(url)
            self.assertEqual(res.status_code, 302, url)
            self.assertTrue(res["Location"].startswith("/login/"), url)

    def test_anonymous_api_gets_401_json(self):
        for url in self.api_urls:
            res = self.client.post(url, data="{}", content_type="application/json")
            self.assertEqual(res.status_code, 401, url)
            self.assertIn("error", res.json())

    def test_admin_can_open_every_page(self):
        self.login(self.admin)
        for url in self.get_urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_coordinator_and_cabo_have_no_access_by_default(self):
        for user in (self.coord, self.cabo):
            self.login(user)
            for url in self.get_urls:
                self.assertEqual(self.client.get(url).status_code, 403, (user.role, url))
            for url in self.post_urls:
                self.assertEqual(self.client.post(url).status_code, 403, (user.role, url))
            for url in self.api_urls:
                res = self.client.post(url, data="{}", content_type="application/json")
                self.assertEqual(res.status_code, 403, (user.role, url))
                self.assertIn("error", res.json())
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.status, ConnectionStatus.CONNECTED)

    def test_view_only_permission_lists_but_cannot_change(self):
        grant(self.a, Role.COORDENADOR, "whatsapp", view=True)
        self.login(self.coord)
        res = self.client.get(reverse("whatsapp:connections"))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "Nova conexão</a>")
        self.assertNotContains(res, self.url("connection_delete", self.conn))
        self.assertEqual(self.client.get(reverse("whatsapp:connection_new")).status_code, 403)
        self.assertEqual(self.client.post(self.url("connection_disable", self.conn)).status_code, 403)
        self.assertEqual(self.client.post(reverse("whatsapp:connection_new"), meta_form()).status_code, 403)
        self.assertEqual(WhatsAppConnection.objects.filter(campaign=self.a).count(), 1)

    def test_edit_permission_allows_changes(self):
        grant(self.a, Role.COORDENADOR, "whatsapp", view=True, edit=True)
        self.login(self.coord)
        res = self.client.post(self.url("connection_disable", self.conn))
        self.assertEqual(res.status_code, 302)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.status, ConnectionStatus.DISABLED)

    def test_super_admin_is_sent_to_super_panel(self):
        self.login(self.super_admin)
        res = self.client.get(reverse("whatsapp:connections"))
        self.assertEqual((res.status_code, res["Location"]), (302, "/super/"))

    def test_actions_reject_get(self):
        self.login(self.admin)
        for url in self.post_urls + self.api_urls:
            self.assertEqual(self.client.get(url).status_code, 405, url)

    def test_actions_require_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        res = client.post(self.url("connection_delete", self.conn))
        self.assertEqual(res.status_code, 403)
        self.assertTrue(WhatsAppConnection.objects.filter(pk=self.conn.pk).exists())


# ------------------------------------------------------------------------------------------------ Isolamento entre campanhas


class CampaignIsolationTests(WhatsAppViewTestCase):
    def setUp(self):
        super().setUp()
        self.conn_b = make_connection(self.b, name="Conexão da campanha B")
        self.login(self.admin)

    def test_other_campaign_connection_is_404_everywhere(self):
        for name in ("connection_edit", "connection_webhook", "connection_check"):
            self.assertEqual(self.client.get(self.url(name, self.conn_b)).status_code, 404, name)
        for name in ("connection_test", "connection_default", "connection_disable", "connection_enable", "connection_delete"):
            self.assertEqual(self.client.post(self.url(name, self.conn_b)).status_code, 404, name)
        for name in ("api_test_connection", "api_send_test_message", "api_register_webhook"):
            res = self.client.post(self.url(name, self.conn_b), data="{}", content_type="application/json")
            self.assertEqual(res.status_code, 404, name)
        self.assertEqual(self.client.post(self.url("connection_edit", self.conn_b), meta_form(name="Invadida")).status_code, 404)
        self.conn_b.refresh_from_db()
        self.assertEqual((self.conn_b.name, self.conn_b.status), ("Conexão da campanha B", ConnectionStatus.CONNECTED))

    def test_unknown_uuid_is_404(self):
        res = self.client.get("/painel/whatsapp/00000000-0000-0000-0000-000000000000/editar/")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.client.get("/painel/whatsapp/nao-e-uuid/editar/").status_code, 404)

    def test_list_shows_only_own_connections_and_no_foreign_data(self):
        mine = make_connection(self.a, name="Minha conexão", provider="SANDBOX")
        res = self.client.get(reverse("whatsapp:connections"))
        self.assertContains(res, "Minha conexão")
        self.assertNotContains(res, "Conexão da campanha B")
        self.assertNotContains(res, self.conn_b.webhook_token)
        self.assertContains(res, self.url("connection_edit", mine))
        self.assertNotContains(res, str(self.conn_b.pk))

    def test_admin_of_other_campaign_cannot_touch_ours(self):
        mine = make_connection(self.a, name="Minha")
        self.login(self.admin_b)
        self.assertEqual(self.client.post(self.url("connection_delete", mine)).status_code, 404)
        self.assertTrue(WhatsAppConnection.objects.filter(pk=mine.pk).exists())

    def test_default_flag_is_per_campaign(self):
        mine = make_connection(self.a, name="Minha", provider="SANDBOX")
        theirs_default = make_connection(self.b, name="Padrão de B", provider="SANDBOX", is_default=True)
        self.client.post(self.url("connection_default", mine))
        theirs_default.refresh_from_db()
        self.assertTrue(theirs_default.is_default)


# ------------------------------------------------------------------------------------------------ Listagem


class ListPageTests(WhatsAppViewTestCase):
    def test_empty_state(self):
        self.login(self.admin)
        res = self.client.get(reverse("whatsapp:connections"))
        self.assertContains(res, "Nenhuma conexão cadastrada")
        self.assertContains(res, "Resolução TSE nº 23.610/2019")
        self.assertContains(res, "consentimento")

    def test_cards_show_status_provider_and_actions(self):
        meta = make_connection(self.a, name="Oficial", is_default=True, phone_number="+55 11 98765-4321", rate_per_minute=30)
        sandbox = make_connection(self.a, name="Treino", provider="SANDBOX", status=ConnectionStatus.ERROR, last_error="Falhou por algum motivo")
        disabled = make_connection(self.a, name="Parada", provider="TWILIO", status=ConnectionStatus.DISABLED)
        self.login(self.admin)
        res = self.client.get(reverse("whatsapp:connections"))
        for text in ("Oficial", "Padrão", "Conectado", "+55 11 98765-4321", "30 msgs/min", "Treino", "Simulador", "Falhou por algum motivo", "Parada", "Desativado"):
            self.assertContains(res, text)
        self.assertContains(res, self.url("connection_test", meta))
        self.assertContains(res, self.url("connection_enable", disabled))  # desativada → "Ativar"
        self.assertContains(res, self.url("connection_disable", meta))
        self.assertContains(res, self.url("connection_edit", sandbox))
        self.assertNotContains(res, self.url("connection_default", sandbox))  # com erro não pode ser a padrão
        self.assertNotContains(res, self.url("connection_default", meta))  # já é a padrão

    def test_connection_names_are_escaped(self):
        make_connection(self.a, name="<script>alert(1)</script>", provider="SANDBOX")
        self.login(self.admin)
        res = self.client.get(reverse("whatsapp:connections"))
        self.assertNotContains(res, "<script>alert(1)</script>")
        self.assertContains(res, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_delete_button_disabled_while_broadcast_is_active(self):
        conn = make_connection(self.a)
        Broadcast.objects.create(campaign=self.a, name="Em andamento", connection=conn, status=BroadcastStatus.RUNNING)
        self.login(self.admin)
        res = self.client.get(reverse("whatsapp:connections"))
        self.assertContains(res, "Em uso por 1 disparo")

    def test_warning_without_connected_connection(self):
        make_connection(self.a, status=ConnectionStatus.ERROR, last_error="x")
        self.login(self.admin)
        self.assertContains(self.client.get(reverse("whatsapp:connections")), "Nenhuma conexão ativa")


# ------------------------------------------------------------------------------------------------ Assistente


class WizardTests(WhatsAppViewTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def test_step_one_lists_all_providers(self):
        res = self.client.get(reverse("whatsapp:connection_new"))
        self.assertEqual(res.status_code, 200)
        for p in PROVIDERS:
            self.assertContains(res, p.label)
            self.assertContains(res, f"?provider={p.key}")
        self.assertContains(res, "Oficial")
        self.assertContains(res, "Simulador")
        self.assertContains(res, "Resolução TSE nº 23.610/2019")
        self.assertNotContains(res, "Z-API")

    def test_step_two_renders_for_every_provider(self):
        for p in PROVIDERS:
            res = self.client.get(reverse("whatsapp:connection_new"), {"provider": p.key})
            self.assertEqual(res.status_code, 200, p.key)
            self.assertContains(res, p.label)
            for spec in p.fields:
                self.assertContains(res, f'name="cred_{spec.name}"')
            self.assertContains(res, 'name="rate_per_minute"')
            self.assertContains(res, 'name="name"')
            self.assertContains(res, "Como o WhatsApp limita os envios?")

    def test_secret_fields_render_as_password_inputs(self):
        res = self.client.get(reverse("whatsapp:connection_new"), {"provider": "META_CLOUD"})
        html = res.content.decode()
        self.assertRegex(html, r'<input[^>]*type="password"[^>]*name="cred_access_token"|<input[^>]*name="cred_access_token"[^>]*type="password"')
        self.assertContains(res, "segredo")

    def test_unknown_provider_falls_back_to_step_one(self):
        res = self.client.get(reverse("whatsapp:connection_new"), {"provider": "ZAPI"})
        self.assertContains(res, "Escolha o provedor")
        res = self.client.post(reverse("whatsapp:connection_new"), meta_form(provider="EVOLUTION"))
        self.assertRedirects(res, reverse("whatsapp:connection_new"), fetch_redirect_response=False)
        self.assertFalse(WhatsAppConnection.objects.exists())

    def test_create_saves_encrypted_draft_with_token_and_goes_to_webhook_step(self):
        res = self.client.post(reverse("whatsapp:connection_new"), meta_form(phone_number="+55 11 98765-4321", rate_per_minute="35"))
        conn = WhatsAppConnection.objects.get()
        self.assertRedirects(res, self.url("connection_webhook", conn), fetch_redirect_response=False)
        self.assertEqual(
            (conn.campaign_id, conn.provider, conn.status, conn.name, conn.rate_per_minute, conn.phone_number),
            (self.a.pk, "META_CLOUD", ConnectionStatus.DRAFT, "WhatsApp oficial", 35, "+55 11 98765-4321"),
        )
        self.assertTrue(conn.is_default)  # a primeira conexão vira a padrão
        self.assertGreaterEqual(len(conn.webhook_token), 24)
        for secret in (META_TOKEN, META_APP_SECRET):
            self.assertNotIn(secret, conn.credentials)
        stored = decrypt_json(conn.credentials)
        self.assertEqual(stored["access_token"], META_TOKEN)
        self.assertEqual(stored["phone_number_id"], "123456789012345")

    def test_create_is_audited_without_secrets(self):
        self.client.post(reverse("whatsapp:connection_new"), meta_form())
        conn = WhatsAppConnection.objects.get()
        log = AuditLog.objects.get(action="whatsapp.connection_create")
        self.assertEqual((log.campaign_id, log.user_id, log.entity, log.entity_id), (self.a.pk, self.admin.pk, "WhatsAppConnection", str(conn.pk)))
        dumped = json.dumps(log.details)
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, dumped)
        self.assertEqual(log.details["provider"], "META_CLOUD")

    def test_second_connection_does_not_steal_default(self):
        first = make_connection(self.a, name="Primeira", is_default=True, provider="SANDBOX")
        self.client.post(reverse("whatsapp:connection_new"), {"provider": "SANDBOX", "name": "Segunda", "rate_per_minute": "10", "cred_failure_rate": ""})
        first.refresh_from_db()
        self.assertTrue(first.is_default)
        self.assertFalse(WhatsAppConnection.objects.get(name="Segunda").is_default)

    def test_invalid_input_rerenders_form_without_saving(self):
        cases = [
            meta_form(name=""),
            meta_form(name="x"),
            meta_form(rate_per_minute="0"),
            meta_form(rate_per_minute="601"),
            meta_form(rate_per_minute="abc"),
            meta_form(cred_phone_number_id="abc"),
            meta_form(cred_phone_number_id=""),
            meta_form(cred_access_token=""),
            meta_form(cred_access_token="token com espacos 1234567890"),
            meta_form(cred_api_version="latest"),
            meta_form(phone_number="<script>"),
        ]
        for data in cases:
            res = self.client.post(reverse("whatsapp:connection_new"), data)
            self.assertEqual(res.status_code, 200, data)
            self.assertContains(res, "field-error")
        self.assertFalse(WhatsAppConnection.objects.exists())

    def test_rejected_form_never_echoes_secrets(self):
        res = self.client.post(reverse("whatsapp:connection_new"), meta_form(rate_per_minute="0"))
        self.assertNotContains(res, META_TOKEN)
        self.assertNotContains(res, META_APP_SECRET)

    def test_twilio_and_dialog360_validation(self):
        bad_twilio = {"provider": "TWILIO", "name": "Twilio", "rate_per_minute": "20", "cred_account_sid": "XX1", "cred_auth_token": "curto", "cred_from_number": "123"}
        res = self.client.post(reverse("whatsapp:connection_new"), bad_twilio)
        self.assertEqual(res.status_code, 200)
        bad_360 = {"provider": "DIALOG360", "name": "360", "rate_per_minute": "20", "cred_api_key": D360_KEY, "cred_base_url": "https://evil.test"}
        res = self.client.post(reverse("whatsapp:connection_new"), bad_360)
        self.assertContains(res, "360dialog")
        self.assertFalse(WhatsAppConnection.objects.exists())

        good_360 = {**bad_360, "cred_base_url": ""}
        self.client.post(reverse("whatsapp:connection_new"), good_360)
        self.assertEqual(WhatsAppConnection.objects.get().provider, "DIALOG360")

    def test_connection_limit_per_campaign(self):
        with mock.patch("apps.whatsapp.views.MAX_CONNECTIONS_PER_CAMPAIGN", 1):
            make_connection(self.a)
            res = self.client.post(reverse("whatsapp:connection_new"), meta_form())
        self.assertContains(res, "Limite de 1 conexões")
        self.assertEqual(WhatsAppConnection.objects.count(), 1)

    def test_missing_encryption_key_shows_friendly_error(self):
        with self.settings(ENCRYPTION_KEY=""):
            res = self.client.post(reverse("whatsapp:connection_new"), meta_form())
        self.assertContains(res, "ENCRYPTION_KEY")
        self.assertFalse(WhatsAppConnection.objects.exists())

    def test_webhook_step_shows_callback_and_verify_token(self):
        self.client.post(reverse("whatsapp:connection_new"), meta_form())
        conn = WhatsAppConnection.objects.get()
        res = self.client.get(self.url("connection_webhook", conn))
        self.assertContains(res, f"https://efind.test/api/webhooks/whatsapp/{conn.webhook_token}/")
        self.assertContains(res, conn.webhook_token)
        self.assertContains(res, "Token de verificação")
        self.assertContains(res, "data-copy=")
        self.assertContains(res, "whatsapp_business_messaging")  # passo a passo do provedor
        self.assertNotContains(res, META_TOKEN)
        self.assertNotContains(res, META_APP_SECRET)
        self.assertNotContains(res, "Registrar webhook automaticamente")

    def test_webhook_step_variants_per_provider(self):
        twilio = make_connection(self.a, provider="TWILIO", name="T")
        res = self.client.get(self.url("connection_webhook", twilio))
        self.assertContains(res, twilio.webhook_token)
        self.assertNotContains(res, "Token de verificação")
        self.assertNotContains(res, TWILIO_AUTH)

        d360 = make_connection(self.a, provider="DIALOG360", name="D")
        res = self.client.get(self.url("connection_webhook", d360))
        self.assertContains(res, "Registrar webhook automaticamente")
        self.assertNotContains(res, D360_KEY)

        sandbox = make_connection(self.a, provider="SANDBOX", name="S")
        res = self.client.get(self.url("connection_webhook", sandbox))
        self.assertContains(res, "O simulador não usa webhook")
        self.assertNotContains(res, "URL de callback")

    def test_webhook_step_warns_when_not_https(self):
        conn = make_connection(self.a)
        with self.settings(APP_URL="http://localhost:8000"):
            res = self.client.get(self.url("connection_webhook", conn))
        self.assertContains(res, "Endereço público necessário")

    def test_test_step_renders_with_message_form(self):
        meta = make_connection(self.a)
        res = self.client.get(self.url("connection_check", meta))
        self.assertContains(res, "Testar conexão")
        self.assertContains(res, "hello_world")
        self.assertContains(res, self.url("api_test_connection", meta))
        self.assertContains(res, self.url("api_send_test_message", meta))
        self.assertContains(res, 'data-mask="phone"')
        sandbox = make_connection(self.a, provider="SANDBOX", name="S")
        res = self.client.get(self.url("connection_check", sandbox))
        self.assertNotContains(res, "hello_world")
        self.assertContains(res, "Nada é enviado de verdade")


# ------------------------------------------------------------------------------------------------ Teste e mensagem de teste


class TestingApiTests(WhatsAppViewTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def post_json(self, url, payload=None):
        return self.client.post(url, data=json.dumps(payload if payload is not None else {}), content_type="application/json")

    def test_successful_test_marks_connected_and_fills_number(self):
        conn = make_connection(self.a, status=ConnectionStatus.DRAFT)
        with mock.patch.object(common, "provider_request", return_value=META_OK):
            res = self.post_json(self.url("api_test_connection", conn))
        data = res.json()
        conn.refresh_from_db()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual((data["status"], data["status_label"], data["status_tone"]), ("CONNECTED", "Conectado", "green"))
        self.assertEqual(conn.status, ConnectionStatus.CONNECTED)
        self.assertEqual(conn.phone_number, "+55 11 98765-4321")
        self.assertIsNotNone(conn.last_tested_at)
        self.assertEqual(conn.last_error, "")
        self.assertTrue(conn.is_default)  # sem padrão na campanha, a primeira conexão testada com sucesso é promovida

    def test_failed_test_marks_error_with_message_and_never_leaks_token(self):
        conn = make_connection(self.a)
        with mock.patch.object(common, "provider_request", return_value=META_AUTH_ERROR):
            res = self.post_json(self.url("api_test_connection", conn))
        conn.refresh_from_db()
        self.assertFalse(res.json()["ok"])
        self.assertEqual(conn.status, ConnectionStatus.ERROR)
        self.assertIn("190", conn.last_error)
        self.assertNotIn(META_TOKEN, res.content.decode())
        self.assertNotIn(META_TOKEN, conn.last_error)

    def test_network_failure_marks_error(self):
        conn = make_connection(self.a)
        with mock.patch.object(common, "provider_request", side_effect=common.ProviderNetworkError("Tempo esgotado", timeout=True)):
            res = self.post_json(self.url("api_test_connection", conn))
        self.assertFalse(res.json()["ok"])
        conn.refresh_from_db()
        self.assertEqual((conn.status, conn.last_error), (ConnectionStatus.ERROR, "Tempo esgotado"))

    def test_sandbox_test_always_passes_without_network(self):
        conn = make_connection(self.a, provider="SANDBOX", status=ConnectionStatus.DRAFT)
        with mock.patch.object(common, "provider_request") as net:
            res = self.post_json(self.url("api_test_connection", conn))
        net.assert_not_called()
        self.assertTrue(res.json()["ok"])
        self.assertIn("nenhuma mensagem real", res.json()["message"])

    def test_unreadable_credentials_give_friendly_error(self):
        conn = make_connection(self.a)
        conn.credentials = "v1:a:b:c"
        conn.save()
        res = self.post_json(self.url("api_test_connection", conn))
        self.assertFalse(res.json()["ok"])
        self.assertIn("credenciais", res.json()["message"])

    def test_test_is_audited(self):
        conn = make_connection(self.a, provider="SANDBOX")
        self.post_json(self.url("api_test_connection", conn))
        log = AuditLog.objects.get(action="whatsapp.connection_test")
        self.assertEqual(log.details, {"provider": "SANDBOX", "kind": "connection", "ok": True})

    def test_form_post_test_redirects_with_message(self):
        conn = make_connection(self.a, provider="SANDBOX", status=ConnectionStatus.DRAFT)
        res = self.client.post(self.url("connection_test", conn), follow=True)
        self.assertRedirects(res, reverse("whatsapp:connections"))
        self.assertContains(res, "Simulador pronto")
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectionStatus.CONNECTED)

    def test_testing_a_disabled_connection_keeps_it_disabled(self):
        conn = make_connection(self.a, provider="SANDBOX", status=ConnectionStatus.DISABLED)
        self.client.post(self.url("connection_test", conn))
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectionStatus.DISABLED)

    def test_send_test_message_free_text(self):
        conn = make_connection(self.a)
        with mock.patch.object(common, "provider_request", return_value=META_SENT) as call:
            res = self.post_json(self.url("api_send_test_message", conn), {"to": "(11) 98765-4321", "text": "Olá, teste!"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        body = call.call_args.kwargs["json_body"]
        self.assertEqual((body["to"], body["type"], body["text"]["body"]), ("5511987654321", "text", "Olá, teste!"))

    def test_send_test_message_with_hello_world_template(self):
        conn = make_connection(self.a)
        with mock.patch.object(common, "provider_request", return_value=META_SENT) as call:
            res = self.post_json(self.url("api_send_test_message", conn), {"to": "11987654321", "text": "", "use_template": True})
        self.assertEqual(res.status_code, 200)
        template = call.call_args.kwargs["json_body"]["template"]
        self.assertEqual((template["name"], template["language"]), ("hello_world", {"code": "en_US"}))

    def test_template_option_is_ignored_for_other_providers(self):
        conn = make_connection(self.a, provider="SANDBOX")
        res = self.post_json(self.url("api_send_test_message", conn), {"to": "11987654321", "text": "", "use_template": True})
        self.assertEqual(res.status_code, 400)
        self.assertIn("text", res.json()["errors"])

    def test_send_test_message_validation(self):
        conn = make_connection(self.a)
        with mock.patch.object(common, "provider_request") as net:
            bad_phone = self.post_json(self.url("api_send_test_message", conn), {"to": "123", "text": "oi"})
            no_text = self.post_json(self.url("api_send_test_message", conn), {"to": "11987654321", "text": "  "})
            bad_json = self.client.post(self.url("api_send_test_message", conn), data="{nope", content_type="application/json")
        net.assert_not_called()
        self.assertEqual(bad_phone.status_code, 400)
        self.assertIn("to", bad_phone.json()["errors"])
        self.assertEqual(no_text.status_code, 400)
        self.assertIn("text", no_text.json()["errors"])
        self.assertEqual(bad_json.status_code, 400)

    def test_send_test_message_provider_error_is_reported(self):
        conn = make_connection(self.a)
        failure = common.HttpResult(400, False, {"error": {"message": "x", "code": 131047}})
        with mock.patch.object(common, "provider_request", return_value=failure):
            res = self.post_json(self.url("api_send_test_message", conn), {"to": "11987654321", "text": "oi"})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json()["ok"])
        self.assertIn("template", res.json()["message"])

    def test_sandbox_message_is_simulated(self):
        conn = make_connection(self.a, provider="SANDBOX", credentials={"failure_rate": "0"})
        with mock.patch.object(common, "provider_request") as net:
            res = self.post_json(self.url("api_send_test_message", conn), {"to": "11987654321", "text": "oi"})
        net.assert_not_called()
        self.assertTrue(res.json()["ok"])
        self.assertIn("simulado", res.json()["message"])

    def test_message_to_disabled_connection_is_refused(self):
        conn = make_connection(self.a, provider="SANDBOX", status=ConnectionStatus.DISABLED)
        res = self.post_json(self.url("api_send_test_message", conn), {"to": "11987654321", "text": "oi"})
        self.assertEqual(res.status_code, 400)

    def test_test_message_is_rate_limited_per_user(self):
        conn = make_connection(self.a, provider="SANDBOX", credentials={"failure_rate": "0"})
        statuses = [
            self.post_json(self.url("api_send_test_message", conn), {"to": "11987654321", "text": "oi"}).status_code for _ in range(11)
        ]
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10], 429)

    def test_register_webhook_only_for_dialog360(self):
        meta = make_connection(self.a)
        self.assertEqual(self.post_json(self.url("api_register_webhook", meta)).status_code, 400)
        d360 = make_connection(self.a, provider="DIALOG360", name="D")
        with mock.patch("apps.whatsapp.views.register_webhook", return_value=(True, "Webhook registrado na 360dialog.")) as register:
            res = self.post_json(self.url("api_register_webhook", d360))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        credentials, url = register.call_args.args
        self.assertEqual(credentials["api_key"], D360_KEY)
        self.assertEqual(url, f"https://efind.test/api/webhooks/whatsapp/{d360.webhook_token}/")

    def test_register_webhook_requires_https(self):
        d360 = make_connection(self.a, provider="DIALOG360", name="D")
        with self.settings(APP_URL="http://localhost:8000"), mock.patch("apps.whatsapp.views.register_webhook") as register:
            res = self.post_json(self.url("api_register_webhook", d360))
        register.assert_not_called()
        self.assertEqual(res.status_code, 400)
        self.assertIn("APP_URL", res.json()["message"])


# ------------------------------------------------------------------------------------------------ Edição e segredos


class EditTests(WhatsAppViewTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)
        self.conn = make_connection(self.a, name="Oficial", phone_number="+55 11 98765-4321", rate_per_minute=20)

    def edit_form(self, **overrides):
        data = {
            "name": "Oficial",
            "phone_number": "+55 11 98765-4321",
            "rate_per_minute": "20",
            "cred_phone_number_id": "123456789012345",
            "cred_business_account_id": "109876543210987",
            "cred_access_token": "",
            "cred_app_secret": "",
            "cred_api_version": "v21.0",
        }
        data.update(overrides)
        return data

    def test_secrets_are_masked_and_never_sent_to_the_browser(self):
        res = self.client.get(self.url("connection_edit", self.conn))
        html = res.content.decode()
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(META_TOKEN, html)
        self.assertNotIn(META_APP_SECRET, html)
        self.assertIn(mask_secret(META_TOKEN), html)
        self.assertIn(mask_secret(META_APP_SECRET), html)
        self.assertContains(res, "deixe em branco para manter")
        self.assertContains(res, "123456789012345")  # campos comuns aparecem pré-preenchidos
        self.assertNotRegex(html, r'name="cred_access_token"[^>]*value=')
        self.assertNotRegex(html, r'value="[^"]*"[^>]*name="cred_access_token"')

    def test_no_page_ever_renders_a_secret(self):
        pages = [
            reverse("whatsapp:connections"),
            self.url("connection_edit", self.conn),
            self.url("connection_webhook", self.conn),
            self.url("connection_check", self.conn),
        ]
        twilio = make_connection(self.a, provider="TWILIO", name="T")
        d360 = make_connection(self.a, provider="DIALOG360", name="D")
        pages += [self.url(n, c) for c in (twilio, d360) for n in ("connection_edit", "connection_webhook", "connection_check")]
        for page in pages:
            res = self.client.get(page)
            self.assertEqual(res.status_code, 200, page)
            body = res.content.decode()
            for secret in ALL_SECRETS:
                self.assertNotIn(secret, body, page)
        for message in (self.client.post(self.url("api_test_connection", self.conn)),):
            for secret in ALL_SECRETS:
                self.assertNotIn(secret, message.content.decode())

    def test_blank_secrets_keep_saved_values(self):
        res = self.client.post(self.url("connection_edit", self.conn), self.edit_form(name="Novo nome", rate_per_minute="45"))
        self.assertRedirects(res, reverse("whatsapp:connections"), fetch_redirect_response=False)
        self.conn.refresh_from_db()
        self.assertEqual((self.conn.name, self.conn.rate_per_minute), ("Novo nome", 45))
        stored = decrypt_json(self.conn.credentials)
        self.assertEqual((stored["access_token"], stored["app_secret"]), (META_TOKEN, META_APP_SECRET))
        self.assertEqual(self.conn.status, ConnectionStatus.CONNECTED)  # sem credencial nova não há novo teste

    def test_new_secret_replaces_old_and_retests(self):
        new_token = "EAAGnovoTOKENnovo0123456789ABCDEF"
        with mock.patch.object(common, "provider_request", return_value=META_OK) as call:
            res = self.client.post(self.url("connection_edit", self.conn), self.edit_form(cred_access_token=new_token), follow=True)
        self.assertContains(res, "testada com sucesso")
        self.assertEqual(call.call_args.kwargs["headers"]["Authorization"], f"Bearer {new_token}")
        self.conn.refresh_from_db()
        stored = decrypt_json(self.conn.credentials)
        self.assertEqual((stored["access_token"], stored["app_secret"]), (new_token, META_APP_SECRET))
        self.assertNotIn(new_token, self.conn.credentials)
        self.assertEqual(self.conn.status, ConnectionStatus.CONNECTED)

    def test_new_secret_that_fails_marks_error(self):
        with mock.patch.object(common, "provider_request", return_value=META_AUTH_ERROR):
            res = self.client.post(
                self.url("connection_edit", self.conn), self.edit_form(cred_access_token="EAAGtokenRUIM0123456789ABCDEF"), follow=True
            )
        self.assertContains(res, "o teste falhou")
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.status, ConnectionStatus.ERROR)

    def test_edit_audit_lists_changed_fields_without_values(self):
        new_token = "EAAGnovoTOKENnovo0123456789ABCDEF"
        with mock.patch.object(common, "provider_request", return_value=META_OK):
            self.client.post(self.url("connection_edit", self.conn), self.edit_form(name="Outro", cred_access_token=new_token))
        log = AuditLog.objects.filter(action="whatsapp.connection_update").latest("created_at")
        self.assertIn("name", log.details["changed_fields"])
        self.assertIn("credentials.access_token", log.details["changed_fields"])
        dumped = json.dumps(log.details)
        for secret in (*ALL_SECRETS, new_token):
            self.assertNotIn(secret, dumped)

    def test_no_changes_is_not_audited(self):
        self.client.post(self.url("connection_edit", self.conn), self.edit_form())
        self.assertFalse(AuditLog.objects.filter(action="whatsapp.connection_update").exists())

    def test_required_secret_cannot_be_cleared_and_validation_errors_rerender(self):
        res = self.client.post(self.url("connection_edit", self.conn), self.edit_form(name="", cred_phone_number_id="abc"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "field-error")
        self.assertNotContains(res, META_TOKEN)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.name, "Oficial")

    def test_optional_secret_can_be_removed(self):
        res = self.client.get(self.url("connection_edit", self.conn))
        self.assertContains(res, 'name="clear_app_secret"')
        self.assertNotContains(res, 'name="clear_access_token"')  # segredo obrigatório não pode ser removido
        self.client.post(self.url("connection_edit", self.conn), self.edit_form(clear_app_secret="on"))
        self.assertNotIn("app_secret", decrypt_json(WhatsAppConnection.objects.get(pk=self.conn.pk).credentials))

    def test_unreadable_credentials_ask_for_secrets_again(self):
        self.conn.credentials = "v1:a:b:c"
        self.conn.save()
        res = self.client.get(self.url("connection_edit", self.conn))
        self.assertContains(res, "Credenciais ilegíveis")
        res = self.client.post(self.url("connection_edit", self.conn), self.edit_form())
        self.assertEqual(res.status_code, 200)  # segredos são obrigatórios de novo
        with mock.patch.object(common, "provider_request", return_value=META_OK):
            res = self.client.post(
                self.url("connection_edit", self.conn),
                self.edit_form(cred_access_token=META_TOKEN, cred_app_secret=META_APP_SECRET),
            )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(decrypt_json(WhatsAppConnection.objects.get(pk=self.conn.pk).credentials)["access_token"], META_TOKEN)

    def test_provider_cannot_be_changed_on_edit(self):
        self.client.post(self.url("connection_edit", self.conn), self.edit_form(provider="TWILIO"))
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.provider, "META_CLOUD")

    def test_campaign_cannot_be_changed_on_edit(self):
        self.client.post(self.url("connection_edit", self.conn), self.edit_form(campaign=str(self.b.pk)))
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.campaign_id, self.a.pk)


# ------------------------------------------------------------------------------------------------ Ações da lista


class ActionTests(WhatsAppViewTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def test_set_default_moves_flag_and_is_audited(self):
        first = make_connection(self.a, name="A", is_default=True, provider="SANDBOX")
        second = make_connection(self.a, name="B", provider="SANDBOX")
        res = self.client.post(self.url("connection_default", second), follow=True)
        self.assertContains(res, "agora é a conexão padrão")
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.is_default, second.is_default), (False, True))
        self.assertEqual(WhatsAppConnection.objects.filter(campaign=self.a, is_default=True).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="whatsapp.connection_update", entity_id=str(second.pk)).exists())

    def test_only_connected_connections_can_be_default(self):
        make_connection(self.a, name="A", is_default=True, provider="SANDBOX")
        draft = make_connection(self.a, name="B", provider="SANDBOX", status=ConnectionStatus.DRAFT)
        res = self.client.post(self.url("connection_default", draft), follow=True)
        self.assertContains(res, "Teste a conexão com sucesso")
        draft.refresh_from_db()
        self.assertFalse(draft.is_default)

    def test_disable_and_enable(self):
        conn = make_connection(self.a, name="A", is_default=True, provider="SANDBOX")
        other = make_connection(self.a, name="B", provider="SANDBOX")
        self.client.post(self.url("connection_disable", conn))
        conn.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((conn.status, conn.is_default), (ConnectionStatus.DISABLED, False))
        self.assertTrue(other.is_default)  # a padrão passa para outra conexão ativa
        res = self.client.post(self.url("connection_enable", conn), follow=True)
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectionStatus.CONNECTED)
        self.assertContains(res, "reativada")

    def test_enable_with_failing_test_goes_to_error(self):
        conn = make_connection(self.a, status=ConnectionStatus.DISABLED)
        with mock.patch.object(common, "provider_request", return_value=META_AUTH_ERROR):
            res = self.client.post(self.url("connection_enable", conn), follow=True)
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectionStatus.ERROR)
        self.assertContains(res, "o teste falhou")

    def test_disabled_connection_is_not_used_by_registry(self):
        from apps.whatsapp.registry import get_default_connection

        conn = make_connection(self.a, is_default=True, provider="SANDBOX")
        self.assertEqual(get_default_connection(self.a.pk), conn)
        self.client.post(self.url("connection_disable", conn))
        self.assertIsNone(get_default_connection(self.a.pk))

    def test_delete_removes_connection_and_audits(self):
        conn = make_connection(self.a, name="Apagar", is_default=True, provider="SANDBOX")
        other = make_connection(self.a, name="Fica", provider="SANDBOX")
        res = self.client.post(self.url("connection_delete", conn), follow=True)
        self.assertContains(res, "excluída")
        self.assertFalse(WhatsAppConnection.objects.filter(pk=conn.pk).exists())
        other.refresh_from_db()
        self.assertTrue(other.is_default)
        log = AuditLog.objects.get(action="whatsapp.connection_delete")
        self.assertEqual((log.entity_id, log.details["name"]), (str(conn.pk), "Apagar"))

    def test_delete_blocked_while_broadcasts_use_the_connection(self):
        conn = make_connection(self.a, name="Em uso")
        for status in (BroadcastStatus.RUNNING, BroadcastStatus.SCHEDULED, BroadcastStatus.PAUSED):
            broadcast = Broadcast.objects.create(campaign=self.a, name=f"D {status}", connection=conn, status=status)
            res = self.client.post(self.url("connection_delete", conn), follow=True)
            self.assertContains(res, "sendo usada por 1 disparo")
            self.assertTrue(WhatsAppConnection.objects.filter(pk=conn.pk).exists(), status)
            broadcast.delete()

    def test_delete_allowed_when_only_finished_broadcasts_exist(self):
        conn = make_connection(self.a, name="Antiga")
        Broadcast.objects.create(campaign=self.a, name="Concluído", connection=conn, status=BroadcastStatus.COMPLETED)
        self.client.post(self.url("connection_delete", conn))
        self.assertFalse(WhatsAppConnection.objects.filter(pk=conn.pk).exists())
        self.assertEqual(Broadcast.objects.filter(campaign=self.a).count(), 1)  # o histórico do disparo permanece

    def test_test_action_is_rate_limited(self):
        conn = make_connection(self.a, provider="SANDBOX")
        for _ in range(30):
            self.client.post(self.url("connection_test", conn))
        res = self.client.post(self.url("connection_test", conn), follow=True)
        self.assertContains(res, "Muitos testes seguidos")
