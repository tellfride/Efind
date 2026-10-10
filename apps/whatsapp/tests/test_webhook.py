"""Registro de provedores, aplicação dos eventos de webhook e a view pública /api/webhooks/whatsapp/<token>/."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest import mock
from urllib.parse import urlencode

from django.test import Client, TestCase
from django.utils import timezone

from apps.auditlog.models import AuditLog
from apps.core.constants import BroadcastStatus, ConnectionStatus, MessageStatus, Role
from apps.core.crypto import decrypt_json
from apps.messaging.models import Broadcast, BroadcastMessage
from apps.whatsapp import registry
from apps.whatsapp.models import InboundMessage
from apps.whatsapp.providers.cloud_api import compute_cloud_signature
from apps.whatsapp.providers.meta_cloud import MetaCloudProvider
from apps.whatsapp.providers.sandbox import SandboxProvider
from apps.whatsapp.providers.twilio import TwilioProvider, compute_twilio_signature
from apps.whatsapp.types import WebhookEvent
from apps.whatsapp.webhook import apply_webhook_events

from .helpers import (
    META_APP_SECRET,
    META_TOKEN,
    TWILIO_AUTH,
    crypto_settings,
    make_campaign,
    make_connection,
    make_user,
    make_voter,
)


@crypto_settings
class RegistryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("alfa")

    def test_credentials_are_stored_encrypted_and_round_trip(self):
        conn = make_connection(self.campaign)
        self.assertNotIn(META_TOKEN, conn.credentials)
        self.assertTrue(conn.credentials.startswith("v1:"))
        self.assertEqual(decrypt_json(conn.credentials)["access_token"], META_TOKEN)
        provider = registry.provider_for_connection(conn)
        self.assertIsInstance(provider, MetaCloudProvider)
        self.assertEqual(provider.creds["access_token"], META_TOKEN)
        self.assertEqual(provider.creds["phone_number_id"], "123456789012345")

    def test_injects_status_callback_and_ids(self):
        conn = make_connection(self.campaign, provider="TWILIO")
        provider = registry.provider_for_connection(conn)
        self.assertIsInstance(provider, TwilioProvider)
        self.assertEqual(provider.creds["status_callback_url"], f"https://efind.test/api/webhooks/whatsapp/{conn.webhook_token}/")
        self.assertEqual(provider.creds["__connection_id"], str(conn.pk))
        self.assertEqual(provider.creds["__campaign_id"], str(self.campaign.pk))

    def test_without_events_omits_ids(self):
        conn = make_connection(self.campaign, provider="SANDBOX", credentials={"failureRate": "0.05"})
        provider = registry.provider_for_connection(conn, with_events=False)
        self.assertIsInstance(provider, SandboxProvider)
        self.assertIsNone(provider.target)
        self.assertEqual(provider.failure_rate, 0.05)  # aceita o formato camelCase do seed_demo
        with_events = registry.provider_for_connection(conn)
        self.assertEqual(str(with_events.target.id), str(conn.pk))
        self.assertEqual(str(with_events.target.campaign_id), str(self.campaign.pk))

    def test_unknown_provider_and_lookup(self):
        self.assertIsNone(registry.get_provider_definition("ZAPI"))
        self.assertEqual(registry.get_provider_definition("TWILIO").key, "TWILIO")
        conn = make_connection(self.campaign)
        conn.provider = "ZAPI"
        with self.assertRaises(ValueError):
            registry.provider_for_connection(conn)

    def test_default_connection_selection(self):
        other = make_campaign("beta")
        self.assertIsNone(registry.get_default_connection(self.campaign.pk))
        make_connection(self.campaign, name="rascunho", status=ConnectionStatus.DRAFT, is_default=True)
        make_connection(other, name="de outra campanha", is_default=True)
        self.assertIsNone(registry.get_default_connection(self.campaign.pk))
        first = make_connection(self.campaign, name="a", provider="SANDBOX")
        self.assertEqual(registry.get_default_connection(self.campaign.pk), first)  # primeira conectada
        default = make_connection(self.campaign, name="b", provider="SANDBOX", is_default=True)
        self.assertEqual(registry.get_default_connection(self.campaign.pk), default)
        default.status = ConnectionStatus.DISABLED
        default.save()
        self.assertEqual(registry.get_default_connection(self.campaign.pk), first)  # padrão inativo não vale


@crypto_settings
class ApplyEventsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.b = make_campaign("beta")
        cls.admin_a = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.conn_a = make_connection(cls.a, provider="SANDBOX")
        cls.conn_b = make_connection(cls.b, provider="SANDBOX")
        cls.broadcast_a = Broadcast.objects.create(campaign=cls.a, name="Disparo A", connection=cls.conn_a, status=BroadcastStatus.RUNNING)
        cls.broadcast_b = Broadcast.objects.create(campaign=cls.b, name="Disparo B", connection=cls.conn_b, status=BroadcastStatus.RUNNING)

    def message(self, broadcast, campaign, pid, status=MessageStatus.SENT, voter=None, phone="5511900000001"):
        return BroadcastMessage.objects.create(
            broadcast=broadcast, campaign=campaign, voter=voter, phone=phone, rendered_body="Olá", status=status, provider_message_id=pid
        )

    def status_event(self, pid, status, error=""):
        return WebhookEvent(kind="status", provider_message_id=pid, status=status, error=error)

    def test_status_moves_forward_only(self):
        msg = self.message(self.broadcast_a, self.a, "wamid.1")
        result = apply_webhook_events(self.conn_a, [self.status_event("wamid.1", "DELIVERED")])
        msg.refresh_from_db()
        self.assertEqual((result.matched, result.updated), (1, 1))
        self.assertEqual(msg.status, MessageStatus.DELIVERED)
        self.assertIsNotNone(msg.delivered_at)

        apply_webhook_events(self.conn_a, [self.status_event("wamid.1", "READ")])
        msg.refresh_from_db()
        self.assertEqual(msg.status, MessageStatus.READ)
        self.assertIsNotNone(msg.read_at)

        # eventos atrasados/duplicados e falha tardia não regridem o status
        for late in ("SENT", "DELIVERED", "FAILED"):
            apply_webhook_events(self.conn_a, [self.status_event("wamid.1", late)])
        msg.refresh_from_db()
        self.assertEqual(msg.status, MessageStatus.READ)
        self.assertEqual(msg.error, "")

    def test_events_in_one_batch_are_applied_in_order(self):
        msg = self.message(self.broadcast_a, self.a, "wamid.2")
        apply_webhook_events(
            self.conn_a, [self.status_event("wamid.2", "READ"), self.status_event("wamid.2", "SENT"), self.status_event("wamid.2", "DELIVERED")]
        )
        msg.refresh_from_db()
        self.assertEqual(msg.status, MessageStatus.READ)

    def test_failure_sets_error_when_not_delivered(self):
        msg = self.message(self.broadcast_a, self.a, "wamid.3")
        apply_webhook_events(self.conn_a, [self.status_event("wamid.3", "FAILED", "Número inválido")])
        msg.refresh_from_db()
        self.assertEqual((msg.status, msg.error), (MessageStatus.FAILED, "Número inválido"))

    def test_other_campaign_messages_are_never_touched(self):
        msg_b = self.message(self.broadcast_b, self.b, "wamid.shared")
        result = apply_webhook_events(self.conn_a, [self.status_event("wamid.shared", "READ")])
        msg_b.refresh_from_db()
        self.assertEqual(result.matched, 0)
        self.assertEqual(msg_b.status, MessageStatus.SENT)

    def test_empty_provider_id_never_matches(self):
        msg = self.message(self.broadcast_a, self.a, "", status=MessageStatus.PENDING)
        result = apply_webhook_events(self.conn_a, [self.status_event("", "DELIVERED")])
        msg.refresh_from_db()
        self.assertEqual(result.matched, 0)
        self.assertEqual(msg.status, MessageStatus.PENDING)

    def test_broadcast_counters_are_refreshed(self):
        self.message(self.broadcast_a, self.a, "wamid.c1")
        self.message(self.broadcast_a, self.a, "wamid.c2")
        apply_webhook_events(self.conn_a, [self.status_event("wamid.c1", "READ"), self.status_event("wamid.c2", "DELIVERED")])
        self.broadcast_a.refresh_from_db()
        self.assertEqual(self.broadcast_a.read_count, 1)
        self.assertEqual(self.broadcast_a.delivered_count, 2)

    def test_counter_failure_does_not_break_webhook(self):
        msg = self.message(self.broadcast_a, self.a, "wamid.c3")
        with mock.patch("apps.whatsapp.webhook.counters.refresh_broadcast_counters", side_effect=NotImplementedError):
            result = apply_webhook_events(self.conn_a, [self.status_event("wamid.c3", "DELIVERED")])
        msg.refresh_from_db()
        self.assertEqual(result.updated, 1)
        self.assertEqual(msg.status, MessageStatus.DELIVERED)

    # ------------------------------------------------------------------ Mensagens recebidas

    def inbound(self, phone, body):
        return WebhookEvent(kind="inbound", from_phone=phone, body=body)

    def test_opt_out_keyword_unsubscribes_voter_and_skips_pending(self):
        voter = make_voter(self.a, self.admin_a, 1, whatsapp_opt_in=True, consent_at=timezone.now())
        other_voter = make_voter(self.a, self.admin_a, 2)
        pending = self.message(self.broadcast_a, self.a, "", MessageStatus.PENDING, voter=voter, phone=voter.phone)
        sent = self.message(self.broadcast_a, self.a, "wamid.s", MessageStatus.SENT, voter=voter, phone=voter.phone)
        other_pending = self.message(self.broadcast_a, self.a, "", MessageStatus.PENDING, voter=other_voter, phone=other_voter.phone)

        result = apply_webhook_events(self.conn_a, [self.inbound(voter.phone, " Sair! ")])

        voter.refresh_from_db()
        other_voter.refresh_from_db()
        pending.refresh_from_db()
        sent.refresh_from_db()
        other_pending.refresh_from_db()
        self.assertEqual((result.inbound, result.opt_outs), (1, 1))
        self.assertIsNotNone(voter.opt_out_at)
        self.assertIsNone(other_voter.opt_out_at)
        self.assertEqual((pending.status, pending.error), (MessageStatus.SKIPPED, "Descadastrado"))
        self.assertEqual(sent.status, MessageStatus.SENT)
        self.assertEqual(other_pending.status, MessageStatus.PENDING)
        inbound = InboundMessage.objects.get()
        self.assertTrue(inbound.is_opt_out)
        self.assertEqual((inbound.voter_id, inbound.campaign_id, inbound.connection_id), (voter.pk, self.a.pk, self.conn_a.pk))

        log = AuditLog.objects.get(action="voter.opt_out")
        self.assertEqual((log.campaign_id, log.entity, log.entity_id), (self.a.pk, "Voter", str(voter.pk)))
        self.assertNotIn(voter.phone, json.dumps(log.details))
        self.assertNotIn(voter.name, json.dumps(log.details))

    def test_second_opt_out_is_not_audited_twice(self):
        voter = make_voter(self.a, self.admin_a, 3)
        apply_webhook_events(self.conn_a, [self.inbound(voter.phone, "PARAR")])
        first = voter.__class__.objects.get(pk=voter.pk).opt_out_at
        apply_webhook_events(self.conn_a, [self.inbound(voter.phone, "parar")])
        self.assertEqual(AuditLog.objects.filter(action="voter.opt_out").count(), 1)
        self.assertEqual(voter.__class__.objects.get(pk=voter.pk).opt_out_at, first)

    def test_regular_reply_is_recorded_without_opt_out(self):
        voter = make_voter(self.a, self.admin_a, 4)
        apply_webhook_events(self.conn_a, [self.inbound(voter.phone, "Quero saber mais sobre a proposta")])
        voter.refresh_from_db()
        inbound = InboundMessage.objects.get()
        self.assertFalse(inbound.is_opt_out)
        self.assertIsNone(voter.opt_out_at)
        self.assertFalse(AuditLog.objects.filter(action="voter.opt_out").exists())

    def test_unknown_sender_is_recorded_without_voter(self):
        result = apply_webhook_events(self.conn_a, [self.inbound("5521955550000", "SAIR")])
        inbound = InboundMessage.objects.get()
        self.assertEqual((result.inbound, result.opt_outs), (1, 0))
        self.assertIsNone(inbound.voter)
        self.assertTrue(inbound.is_opt_out)

    def test_voter_from_other_campaign_is_never_unsubscribed(self):
        voter_b = make_voter(self.b, self.admin_b, 5)
        apply_webhook_events(self.conn_a, [self.inbound(voter_b.phone, "SAIR")])
        voter_b.refresh_from_db()
        self.assertIsNone(voter_b.opt_out_at)
        self.assertIsNone(InboundMessage.objects.get().voter)

    def test_sender_without_ninth_digit_matches_registered_voter(self):
        voter = make_voter(self.a, self.admin_a, 6)
        voter.phone = "5511987654321"
        voter.save()
        apply_webhook_events(self.conn_a, [self.inbound("551187654321", "SAIR")])
        voter.refresh_from_db()
        self.assertIsNotNone(voter.opt_out_at)

    def test_long_body_is_truncated(self):
        apply_webhook_events(self.conn_a, [self.inbound("5521955550001", "x" * 10000)])
        self.assertEqual(len(InboundMessage.objects.get().body), 4096)


# ------------------------------------------------------------------------------------------------ View pública


@crypto_settings
class WebhookViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.meta = make_connection(cls.a, provider="META_CLOUD", name="Meta")
        cls.twilio = make_connection(cls.a, provider="TWILIO", name="Twilio")
        cls.d360 = make_connection(cls.a, provider="DIALOG360", name="360")
        cls.broadcast = Broadcast.objects.create(campaign=cls.a, name="D", connection=cls.meta, status=BroadcastStatus.RUNNING)

    def url(self, conn):
        return f"/api/webhooks/whatsapp/{conn.webhook_token}/"

    def message(self, pid, status=MessageStatus.SENT):
        return BroadcastMessage.objects.create(
            broadcast=self.broadcast, campaign=self.a, phone="5511900000001", rendered_body="Oi", status=status, provider_message_id=pid
        )

    def meta_body(self, pid, status):
        return json.dumps(
            {"entry": [{"changes": [{"value": {"statuses": [{"id": pid, "status": status, "timestamp": "1760000000"}]}}]}]}
        ).encode()

    def post_meta(self, body, secret=META_APP_SECRET, signature=None, client=None):
        headers = {}
        sig = signature if signature is not None else (compute_cloud_signature(secret, body) if secret else None)
        if sig:
            headers["HTTP_X_HUB_SIGNATURE_256"] = sig
        return (client or self.client).post(self.url(self.meta), data=body, content_type="application/json", **headers)

    # ---------------------------------------------------------------- verificação

    def test_verification_handshake(self):
        res = self.client.get(self.url(self.meta), {"hub.mode": "subscribe", "hub.verify_token": self.meta.webhook_token, "hub.challenge": "98765"})
        self.assertEqual((res.status_code, res.content.decode()), (200, "98765"))
        self.assertTrue(res["Content-Type"].startswith("text/plain"))

    def test_verification_with_wrong_token_is_403(self):
        res = self.client.get(self.url(self.meta), {"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "98765"})
        self.assertEqual(res.status_code, 403)
        self.assertNotIn("98765", res.content.decode())

    def test_other_connections_token_does_not_verify(self):
        res = self.client.get(self.url(self.meta), {"hub.mode": "subscribe", "hub.verify_token": self.twilio.webhook_token, "hub.challenge": "1"})
        self.assertEqual(res.status_code, 403)

    def test_plain_get_is_harmless(self):
        res = self.client.get(self.url(self.meta))
        self.assertEqual((res.status_code, res.content.decode()), (200, "ok"))

    # ---------------------------------------------------------------- 404 / métodos

    def test_unknown_token_is_404(self):
        self.assertEqual(self.client.get("/api/webhooks/whatsapp/nao-existe/").status_code, 404)
        self.assertEqual(self.client.post("/api/webhooks/whatsapp/nao-existe/", data="{}", content_type="application/json").status_code, 404)

    def test_disabled_connection_is_404(self):
        conn = make_connection(self.a, provider="SANDBOX", status=ConnectionStatus.DISABLED)
        self.assertEqual(self.client.post(self.url(conn), data="{}", content_type="application/json").status_code, 404)
        self.assertEqual(self.client.get(self.url(conn)).status_code, 404)

    def test_only_get_and_post_are_allowed(self):
        for method in ("put", "delete", "patch"):
            self.assertEqual(getattr(self.client, method)(self.url(self.meta)).status_code, 405, method)

    def test_no_login_and_no_csrf_required(self):
        pid = "wamid.csrf"
        msg = self.message(pid)
        client = Client(enforce_csrf_checks=True)
        res = self.post_meta(self.meta_body(pid, "delivered"), client=client)
        msg.refresh_from_db()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(msg.status, MessageStatus.DELIVERED)

    # ---------------------------------------------------------------- assinatura Meta

    def test_bad_signature_is_401_and_nothing_changes(self):
        msg = self.message("wamid.bad")
        body = self.meta_body("wamid.bad", "read")
        for signature in ("sha256=" + "0" * 64, "lixo"):
            self.assertEqual(self.post_meta(body, signature=signature).status_code, 401)
        res = self.post_meta(body, secret=None)  # sem cabeçalho de assinatura, com App Secret configurado
        self.assertEqual(res.status_code, 401)
        msg.refresh_from_db()
        self.assertEqual(msg.status, MessageStatus.SENT)

    def test_signature_of_other_secret_is_rejected(self):
        msg = self.message("wamid.other")
        body = self.meta_body("wamid.other", "read")
        self.assertEqual(self.post_meta(body, secret="outro-app-secret-0123456789").status_code, 401)
        msg.refresh_from_db()
        self.assertEqual(msg.status, MessageStatus.SENT)

    def test_valid_signature_applies_status_update(self):
        msg = self.message("wamid.ok")
        res = self.post_meta(self.meta_body("wamid.ok", "read"))
        msg.refresh_from_db()
        self.assertEqual((res.status_code, res.content.decode()), (200, "ok"))
        self.assertEqual(msg.status, MessageStatus.READ)
        self.broadcast.refresh_from_db()
        self.assertEqual(self.broadcast.read_count, 1)

    def test_meta_without_app_secret_accepts_unsigned(self):
        conn = make_connection(self.a, provider="META_CLOUD", credentials={"phone_number_id": "123456789012345", "access_token": META_TOKEN})
        msg = self.message("wamid.nosecret")
        res = self.client.post(self.url(conn), data=self.meta_body("wamid.nosecret", "delivered"), content_type="application/json")
        msg.refresh_from_db()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(msg.status, MessageStatus.DELIVERED)

    def test_garbage_body_is_200(self):
        self.assertEqual(self.post_meta(b"isto nao e json").status_code, 200)

    def test_processing_error_still_returns_200_without_leaking(self):
        body = self.meta_body("wamid.err", "read")
        with mock.patch("apps.whatsapp.webhook_views.apply_webhook_events", side_effect=RuntimeError("boom 5511987654321")):
            with self.assertLogs("apps.whatsapp.webhook_views", level="ERROR") as logs:
                res = self.post_meta(body)
        self.assertEqual((res.status_code, res.content.decode()), (200, "ok"))
        self.assertNotIn("boom", "".join(logs.output))
        self.assertNotIn("5511987654321", "".join(logs.output))

    def test_oversized_body_is_rejected(self):
        res = self.client.post(self.url(self.meta), data=b"x" * 1_100_000, content_type="application/json")
        self.assertEqual(res.status_code, 413)

    def test_unreadable_credentials_do_not_bypass_signature(self):
        conn = make_connection(self.a, provider="META_CLOUD")
        conn.credentials = "v1:invalido:invalido:invalido"
        conn.save()
        res = self.client.post(self.url(conn), data=self.meta_body("x", "read"), content_type="application/json")
        self.assertEqual(res.status_code, 503)

    def test_inbound_opt_out_through_the_view(self):
        voter = make_voter(self.a, self.admin, 7)
        body = json.dumps({"entry": [{"changes": [{"value": {"messages": [{"from": voter.phone, "type": "text", "text": {"body": "SAIR"}}]}}]}]}).encode()
        self.assertEqual(self.post_meta(body).status_code, 200)
        voter.refresh_from_db()
        self.assertIsNotNone(voter.opt_out_at)

    # ---------------------------------------------------------------- Twilio e 360dialog

    def post_twilio(self, params, signature=None):
        url = f"https://efind.test/api/webhooks/whatsapp/{self.twilio.webhook_token}/"
        sig = signature if signature is not None else compute_twilio_signature(TWILIO_AUTH, url, params.items())
        return self.client.post(
            self.url(self.twilio), data=urlencode(params), content_type="application/x-www-form-urlencoded", HTTP_X_TWILIO_SIGNATURE=sig
        )

    def test_twilio_valid_signature_updates_status(self):
        msg = self.message("SM100")
        res = self.post_twilio({"MessageSid": "SM100", "MessageStatus": "delivered", "To": "whatsapp:+5511900000001"})
        msg.refresh_from_db()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(msg.status, MessageStatus.DELIVERED)

    def test_twilio_invalid_signature_is_401(self):
        msg = self.message("SM101")
        res = self.post_twilio({"MessageSid": "SM101", "MessageStatus": "read"}, signature="AAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        msg.refresh_from_db()
        self.assertEqual(res.status_code, 401)
        self.assertEqual(msg.status, MessageStatus.SENT)

    def test_dialog360_accepts_cloud_format(self):
        msg = self.message("wamid.360")
        res = self.client.post(self.url(self.d360), data=self.meta_body("wamid.360", "delivered"), content_type="application/json")
        msg.refresh_from_db()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(msg.status, MessageStatus.DELIVERED)

    def test_status_message_ids_are_scoped_to_connection_campaign(self):
        other = make_campaign("beta")
        other_broadcast = Broadcast.objects.create(campaign=other, name="B", status=BroadcastStatus.RUNNING)
        foreign = BroadcastMessage.objects.create(
            broadcast=other_broadcast, campaign=other, phone="5511900000009", rendered_body="x", status=MessageStatus.SENT, provider_message_id="wamid.foreign"
        )
        self.assertEqual(self.post_meta(self.meta_body("wamid.foreign", "read")).status_code, 200)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, MessageStatus.SENT)

    def test_old_timestamps_do_not_break_updates(self):
        msg = self.message("wamid.old")
        old = int((timezone.now() - timedelta(days=3)).timestamp())
        body = json.dumps({"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.old", "status": "delivered", "timestamp": str(old)}]}}]}]}).encode()
        self.post_meta(body)
        msg.refresh_from_db()
        self.assertEqual(msg.status, MessageStatus.DELIVERED)
        self.assertLess(msg.delivered_at, timezone.now() - timedelta(days=2))
