"""Lógica pura dos provedores: webhooks, assinaturas, corpos de envio, regras de status e descadastro (sem banco/rede)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest import mock
from urllib.parse import urlencode

from django.test import SimpleTestCase

from apps.whatsapp.credentials import CredentialError, split_credentials, validate_credential
from apps.whatsapp.providers import common
from apps.whatsapp.providers.cloud_api import (
    build_cloud_api_payload,
    compute_cloud_signature,
    parse_cloud_api_send_response,
    parse_cloud_api_webhook_body,
)
from apps.whatsapp.providers.dialog360 import DIALOG360, Dialog360Provider, is_allowed_dialog360_url
from apps.whatsapp.providers.meta_cloud import META_CLOUD, MetaCloudProvider
from apps.whatsapp.providers.sandbox import SANDBOX, SandboxProvider, parse_failure_rate
from apps.whatsapp.providers.twilio import (
    TWILIO,
    TwilioProvider,
    build_twilio_params,
    compute_twilio_signature,
    parse_twilio_webhook_body,
)
from apps.whatsapp.rules import (
    build_status_update,
    inbound_phone_candidates,
    is_opt_out_message,
    next_message_status,
    normalize_opt_out_text,
)
from apps.whatsapp.types import MediaAttachment, OutgoingMessage, TemplateCall, WebhookRequest

TOKEN = "tok_verify_123"


def req(method="POST", body=b"", headers=None, query=None, url="https://efind.test/api/webhooks/whatsapp/x/"):
    return WebhookRequest(method=method, url=url, headers=headers or {}, raw_body=body, query=query or {})


# ------------------------------------------------------------------------------------------------ Meta: webhook

META_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "1",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "statuses": [
                            {"id": "wamid.A", "status": "sent", "timestamp": "1760000000"},
                            {"id": "wamid.A", "status": "delivered", "timestamp": "1760000005"},
                            {"id": "wamid.A", "status": "read", "timestamp": "1760000010"},
                            {
                                "id": "wamid.B",
                                "status": "failed",
                                "timestamp": "1760000020",
                                "errors": [{"code": 131026, "title": "Message undeliverable"}],
                            },
                        ],
                        "messages": [
                            {"from": "5511987654321", "type": "text", "text": {"body": "Sair"}, "timestamp": "1760000030"},
                            {"from": "5511987654322", "type": "button", "button": {"text": "Parar promoções"}},
                            {
                                "from": "5511987654323",
                                "type": "interactive",
                                "interactive": {"type": "button_reply", "button_reply": {"title": "Quero saber mais"}},
                            },
                            {"from": "5511987654324", "type": "image"},
                        ],
                    },
                }
            ],
        }
    ],
}


class MetaWebhookTests(SimpleTestCase):
    def test_parses_statuses_and_messages(self):
        events = META_CLOUD.parse_webhook(req(body=json.dumps(META_PAYLOAD).encode()))
        statuses = [e for e in events if e.kind == "status"]
        inbound = [e for e in events if e.kind == "inbound"]
        self.assertEqual([(e.provider_message_id, e.status) for e in statuses], [
            ("wamid.A", "SENT"), ("wamid.A", "DELIVERED"), ("wamid.A", "READ"), ("wamid.B", "FAILED"),
        ])
        self.assertIsNotNone(statuses[0].timestamp)
        self.assertIn("131026", statuses[3].error)
        self.assertEqual([(e.from_phone, e.body) for e in inbound], [
            ("5511987654321", "Sair"),
            ("5511987654322", "Parar promoções"),
            ("5511987654323", "Quero saber mais"),
            ("5511987654324", "[imagem]"),
        ])

    def test_invalid_payloads_are_ignored(self):
        for body in (b"", b"not json", b"[]", b'{"entry": "x"}', b'{"entry": [{"changes": [{"value": 1}]}]}'):
            self.assertEqual(META_CLOUD.parse_webhook(req(body=body)), [])

    def test_unknown_status_and_missing_id_are_skipped(self):
        payload = {"entry": [{"changes": [{"value": {"statuses": [{"status": "sent"}, {"id": "x", "status": "weird"}]}}]}]}
        self.assertEqual(parse_cloud_api_webhook_body(json.dumps(payload)), [])


class MetaVerificationTests(SimpleTestCase):
    def verify(self, **query):
        return META_CLOUD.handle_verification(req("GET", query=query), {}, TOKEN)

    def test_handshake_returns_challenge(self):
        res = self.verify(**{"hub.mode": "subscribe", "hub.verify_token": TOKEN, "hub.challenge": "1158201444"})
        self.assertEqual((res.status, res.body), (200, "1158201444"))
        self.assertTrue(res.content_type.startswith("text/plain"))

    def test_wrong_token_or_mode_is_forbidden(self):
        self.assertEqual(self.verify(**{"hub.mode": "subscribe", "hub.verify_token": "outro", "hub.challenge": "1"}).status, 403)
        self.assertEqual(self.verify(**{"hub.mode": "unsubscribe", "hub.verify_token": TOKEN, "hub.challenge": "1"}).status, 403)

    def test_challenge_is_not_reflected_when_suspicious(self):
        res = self.verify(**{"hub.mode": "subscribe", "hub.verify_token": TOKEN, "hub.challenge": "<script>alert(1)</script>"})
        self.assertEqual(res.status, 400)

    def test_not_a_verification_request(self):
        self.assertIsNone(self.verify())
        self.assertIsNone(META_CLOUD.handle_verification(req("POST"), {}, TOKEN))


class MetaSignatureTests(SimpleTestCase):
    body = b'{"object":"whatsapp_business_account"}'
    secret = "app-secret-xyz-0123456789"

    def check(self, header, secret=None):
        headers = {"x-hub-signature-256": header} if header is not None else {}
        return META_CLOUD.verify_signature(req(body=self.body, headers=headers), {"app_secret": secret})

    def test_valid_signature(self):
        expected = "sha256=" + hmac.new(self.secret.encode(), self.body, hashlib.sha256).hexdigest()
        self.assertEqual(compute_cloud_signature(self.secret, self.body), expected)
        self.assertTrue(self.check(expected, self.secret))
        self.assertTrue(self.check(expected.upper().replace("SHA256=", "sha256="), self.secret))

    def test_invalid_signature(self):
        self.assertFalse(self.check("sha256=" + "0" * 64, self.secret))
        self.assertFalse(self.check("md5=abc", self.secret))
        self.assertFalse(self.check(None, self.secret))
        other = "sha256=" + hmac.new(b"outra", self.body, hashlib.sha256).hexdigest()
        self.assertFalse(self.check(other, self.secret))

    def test_accepts_when_app_secret_not_configured(self):
        self.assertTrue(self.check(None, None))
        self.assertTrue(self.check("lixo", ""))


# ------------------------------------------------------------------------------------------------ Meta: corpos de envio


class CloudPayloadTests(SimpleTestCase):
    def test_text(self):
        payload = build_cloud_api_payload(OutgoingMessage(to="+55 (11) 98765-4321", text="Olá, Maria!"))
        self.assertEqual(
            payload,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": "5511987654321",
                "type": "text",
                "text": {"body": "Olá, Maria!", "preview_url": True},
            },
        )

    def test_media_with_caption_and_filename(self):
        image = build_cloud_api_payload(
            OutgoingMessage(to="5511987654321", text="Legenda", media=MediaAttachment("IMAGE", "https://x.test/a.png"))
        )
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["image"], {"link": "https://x.test/a.png", "caption": "Legenda"})
        doc = build_cloud_api_payload(
            OutgoingMessage(to="5511987654321", text="", media=MediaAttachment("DOCUMENT", "https://x.test/p.pdf", "plano.pdf"))
        )
        self.assertEqual(doc["document"], {"link": "https://x.test/p.pdf", "filename": "plano.pdf"})
        video = build_cloud_api_payload(OutgoingMessage(to="5511987654321", text="v", media=MediaAttachment("VIDEO", "https://x.test/v.mp4")))
        self.assertEqual(video["type"], "video")

    def test_template_with_parameters(self):
        payload = build_cloud_api_payload(
            OutgoingMessage(
                to="5511987654321", text="", template=TemplateCall("boas_vindas", "pt_BR", ["Maria\nSilva", "Centro"])
            )
        )
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["template"]["name"], "boas_vindas")
        self.assertEqual(payload["template"]["language"], {"code": "pt_BR"})
        body = payload["template"]["components"][0]
        self.assertEqual(body["type"], "body")
        # quebras de linha não são aceitas em parâmetros de template
        self.assertEqual([p["text"] for p in body["parameters"]], ["Maria Silva", "Centro"])

    def test_template_with_media_header_and_without_parameters(self):
        payload = build_cloud_api_payload(
            OutgoingMessage(
                to="5511987654321",
                text="",
                media=MediaAttachment("IMAGE", "https://x.test/a.png"),
                template=TemplateCall("hello_world", "en_US"),
            )
        )
        components = payload["template"]["components"]
        self.assertEqual(components, [{"type": "header", "parameters": [{"type": "image", "image": {"link": "https://x.test/a.png"}}]}])
        plain = build_cloud_api_payload(OutgoingMessage(to="5511987654321", text="", template=TemplateCall("hello_world", "en_US")))
        self.assertNotIn("components", plain["template"])


class CloudSendResponseTests(SimpleTestCase):
    def test_success(self):
        res = parse_cloud_api_send_response(200, {"messages": [{"id": "wamid.XYZ"}]})
        self.assertTrue(res.ok)
        self.assertEqual(res.provider_message_id, "wamid.XYZ")

    def test_error_and_retryable_rules(self):
        permanent = parse_cloud_api_send_response(400, {"error": {"message": "x", "code": 131026}})
        self.assertFalse(permanent.ok)
        self.assertFalse(permanent.retryable)
        self.assertIn("131026", permanent.error)
        for status, code in ((429, None), (500, None), (400, 130429), (400, 131048), (400, 131056), (400, 80007)):
            body = {"error": {"message": "x", "code": code}} if code else {}
            self.assertTrue(parse_cloud_api_send_response(status, body).retryable, (status, code))

    def test_ok_status_without_message_id_is_failure(self):
        res = parse_cloud_api_send_response(200, {})
        self.assertFalse(res.ok)


class MetaProviderHttpTests(SimpleTestCase):
    creds = {"phone_number_id": "123456789012345", "access_token": "EAAGtoken0123456789012345"}

    def test_send_posts_to_graph_with_bearer(self):
        provider = MetaCloudProvider({**self.creds, "api_version": "v22.0"})
        fake = common.HttpResult(status=200, ok=True, data={"messages": [{"id": "wamid.1"}]})
        with mock.patch.object(common, "provider_request", return_value=fake) as call:
            result = provider.send(OutgoingMessage(to="5511987654321", text="oi"))
        self.assertTrue(result.ok)
        args, kwargs = call.call_args
        self.assertEqual(args, ("POST", "https://graph.facebook.com/v22.0/123456789012345/messages"))
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {self.creds['access_token']}")
        self.assertEqual(kwargs["json_body"]["text"]["body"], "oi")

    def test_send_rejects_bad_recipient_without_network(self):
        with mock.patch.object(common, "provider_request") as call:
            result = MetaCloudProvider(self.creds).send(OutgoingMessage(to="123", text="oi"))
        self.assertFalse(result.ok)
        call.assert_not_called()

    def test_network_failure_is_retryable(self):
        with mock.patch.object(common, "provider_request", side_effect=common.ProviderNetworkError("Tempo esgotado", timeout=True)):
            result = MetaCloudProvider(self.creds).send(OutgoingMessage(to="5511987654321", text="oi"))
        self.assertEqual((result.ok, result.retryable), (False, True))

    def test_test_connection_success_and_error(self):
        ok = common.HttpResult(200, True, {"display_phone_number": "+55 11 98765-4321", "verified_name": "Campanha", "quality_rating": "GREEN"})
        with mock.patch.object(common, "provider_request", return_value=ok) as call:
            result = MetaCloudProvider(self.creds).test_connection()
        self.assertTrue(result.ok)
        self.assertEqual(result.phone_number, "+55 11 98765-4321")
        self.assertIn("alta", result.message)
        self.assertEqual(call.call_args.args[0], "GET")
        self.assertIn("fields=display_phone_number,verified_name,quality_rating", call.call_args.args[1])

        bad = common.HttpResult(401, False, {"error": {"message": "Invalid OAuth", "code": 190}})
        with mock.patch.object(common, "provider_request", return_value=bad):
            result = MetaCloudProvider(self.creds).test_connection()
        self.assertFalse(result.ok)
        self.assertIn("190", result.message)

    def test_incomplete_credentials(self):
        self.assertFalse(MetaCloudProvider({}).test_connection().ok)
        self.assertFalse(MetaCloudProvider({}).send(OutgoingMessage(to="5511987654321", text="oi")).ok)


# ------------------------------------------------------------------------------------------------ Twilio


class TwilioSignatureTests(SimpleTestCase):
    url = "https://efind.test/api/webhooks/whatsapp/tok/"
    token = "twilio-auth-token-0123456789"
    params = {"MessageSid": "SM123", "MessageStatus": "delivered", "To": "whatsapp:+5511987654321"}

    def sign(self, url=None, params=None):
        params = params or self.params
        data = (url or self.url) + "".join(k + v for k, v in sorted(params.items()))
        return base64.b64encode(hmac.new(self.token.encode(), data.encode(), hashlib.sha1).digest()).decode()

    def request(self, signature, params=None, url=None):
        body = urlencode(params or self.params).encode()
        return req(body=body, headers={"x-twilio-signature": signature}, url=url or self.url)

    def test_known_vector_from_twilio_docs(self):
        sig = compute_twilio_signature(
            "12345",
            "https://mycompany.com/myapp.php?foo=1&bar=2",
            [("Digits", "1234"), ("To", "+18005551212"), ("From", "+14158675310"), ("Caller", "+14158675310"), ("CallSid", "CA1234567890ABCDE")],
        )
        self.assertEqual(sig, "GvWf1cFY/Q7PnoempGyD5oXAezc=")

    def test_valid_signature_matches_independent_computation(self):
        sig = self.sign()
        self.assertEqual(compute_twilio_signature(self.token, self.url, self.params.items()), sig)
        self.assertTrue(TWILIO.verify_signature(self.request(sig), {"auth_token": self.token}))

    def test_rejects_tampered_params_wrong_token_or_missing_header(self):
        sig = self.sign()
        tampered = {**self.params, "MessageStatus": "read"}
        self.assertFalse(TWILIO.verify_signature(self.request(sig, tampered), {"auth_token": self.token}))
        self.assertFalse(TWILIO.verify_signature(self.request(sig), {"auth_token": "outro-token"}))
        self.assertFalse(TWILIO.verify_signature(self.request(""), {"auth_token": self.token}))
        self.assertFalse(TWILIO.verify_signature(self.request(sig), {}))
        self.assertFalse(TWILIO.verify_signature(self.request(sig, url="https://evil.test/x/"), {"auth_token": self.token}))

    def test_accepts_default_port_variants(self):
        sig = self.sign(url="https://efind.test:443/api/webhooks/whatsapp/tok/")
        self.assertTrue(TWILIO.verify_signature(self.request(sig), {"auth_token": self.token}))


class TwilioParserTests(SimpleTestCase):
    def parse(self, **params):
        return TWILIO.parse_webhook(req(body=urlencode(params).encode()))

    def test_status_callbacks(self):
        for raw, expected in (("sent", "SENT"), ("delivered", "DELIVERED"), ("read", "READ"), ("failed", "FAILED"), ("undelivered", "FAILED")):
            (event,) = self.parse(MessageSid="SM1", MessageStatus=raw)
            self.assertEqual((event.kind, event.provider_message_id, event.status), ("status", "SM1", expected))

    def test_queued_and_unknown_statuses_are_ignored(self):
        self.assertEqual(self.parse(MessageSid="SM1", MessageStatus="queued"), [])
        self.assertEqual(self.parse(MessageStatus="sent"), [])

    def test_failure_has_friendly_error(self):
        (event,) = self.parse(MessageSid="SM1", MessageStatus="failed", ErrorCode="63016", ErrorMessage="Fora da janela")
        self.assertTrue(event.error)

    def test_inbound_message(self):
        (event,) = self.parse(From="whatsapp:+5511987654321", Body="SAIR", MessageSid="SM9", SmsStatus="received")
        self.assertEqual((event.kind, event.from_phone, event.body), ("inbound", "5511987654321", "SAIR"))

    def test_params_builder(self):
        creds = {"from_number": "+5511999990000", "status_callback_url": "https://efind.test/cb/"}
        text = build_twilio_params(OutgoingMessage(to="5511987654321", text="Oi"), creds)
        self.assertEqual(text["From"], "whatsapp:+5511999990000")
        self.assertEqual(text["To"], "whatsapp:+5511987654321")
        self.assertEqual((text["Body"], text["StatusCallback"]), ("Oi", "https://efind.test/cb/"))
        media = build_twilio_params(OutgoingMessage(to="5511987654321", text="", media=MediaAttachment("IMAGE", "https://x.test/a.png")), creds)
        self.assertEqual(media["MediaUrl"], "https://x.test/a.png")
        content = build_twilio_params(
            OutgoingMessage(to="5511987654321", text="", template=TemplateCall("HX0123", "pt_BR", ["Maria", "Centro"])), creds
        )
        self.assertEqual(content["ContentSid"], "HX0123")
        self.assertEqual(json.loads(content["ContentVariables"]), {"1": "Maria", "2": "Centro"})
        self.assertNotIn("Body", content)

    def test_send_and_test_connection_use_basic_auth(self):
        creds = {"account_sid": "AC" + "1" * 32, "auth_token": "tok0123456789abcdef", "from_number": "+5511999990000"}
        fake = common.HttpResult(201, True, {"sid": "SM77", "status": "queued"})
        with mock.patch.object(common, "provider_request", return_value=fake) as call:
            result = TwilioProvider(creds).send(OutgoingMessage(to="5511987654321", text="Oi"))
        self.assertTrue(result.ok)
        self.assertEqual(result.provider_message_id, "SM77")
        self.assertEqual(call.call_args.kwargs["auth"], (creds["account_sid"], creds["auth_token"]))
        self.assertTrue(call.call_args.args[1].endswith(f"/Accounts/{creds['account_sid']}/Messages.json"))

        ok = common.HttpResult(200, True, {"friendly_name": "Campanha", "status": "active"})
        with mock.patch.object(common, "provider_request", return_value=ok):
            self.assertTrue(TwilioProvider(creds).test_connection().ok)


# ------------------------------------------------------------------------------------------------ 360dialog / simulador


class Dialog360Tests(SimpleTestCase):
    def test_webhook_uses_cloud_format(self):
        events = DIALOG360.parse_webhook(req(body=json.dumps(META_PAYLOAD).encode()))
        self.assertEqual(len(events), 8)

    def test_base_url_is_restricted_to_360dialog(self):
        self.assertTrue(is_allowed_dialog360_url("https://waba-v2.360dialog.io"))
        for url in ("http://waba-v2.360dialog.io", "https://evil.test", "https://waba-v2.360dialog.io.evil.test", "https://169.254.169.254"):
            self.assertFalse(is_allowed_dialog360_url(url), url)

    def test_send_uses_api_key_header(self):
        fake = common.HttpResult(200, True, {"messages": [{"id": "wamid.D"}]})
        with mock.patch.object(common, "provider_request", return_value=fake) as call:
            result = Dialog360Provider({"api_key": "k" * 20}).send(OutgoingMessage(to="5511987654321", text="oi"))
        self.assertTrue(result.ok)
        self.assertEqual(call.call_args.kwargs["headers"]["D360-API-KEY"], "k" * 20)
        self.assertTrue(call.call_args.args[1].endswith("/messages"))


class SandboxTests(SimpleTestCase):
    def test_send_never_touches_network_and_returns_sbx_id(self):
        provider = SandboxProvider({"failure_rate": "0"})
        with mock.patch.object(common, "provider_request") as net, mock.patch("httpx.request") as raw_http:
            result = provider.send(OutgoingMessage(to="5511987654321", text="Oi"))
        self.assertTrue(result.ok)
        self.assertTrue(result.provider_message_id.startswith("sbx_"))
        net.assert_not_called()
        raw_http.assert_not_called()

    def test_failure_rate_accepts_snake_and_camel_case(self):
        self.assertEqual(SandboxProvider({"failureRate": "0.3"}).failure_rate, 0.3)
        self.assertEqual(SandboxProvider({"failure_rate": "0.2"}).failure_rate, 0.2)
        self.assertEqual(SandboxProvider({}).failure_rate, 0.05)

    def test_simulated_failure(self):
        provider = SandboxProvider({"failure_rate": "0.5"}, rng=lambda: 0.0)
        result = provider.send(OutgoingMessage(to="5511987654321", text="Oi"))
        self.assertFalse(result.ok)
        self.assertFalse(result.retryable)

    def test_schedules_status_events_only_with_connection_ids(self):
        with mock.patch("apps.whatsapp.providers.sandbox.schedule_simulation") as schedule:
            SandboxProvider({"failure_rate": "0"}, rng=lambda: 0.9).send(OutgoingMessage(to="5511987654321", text="Oi"))
            schedule.assert_not_called()
            provider = SandboxProvider({"failure_rate": "0", "__connection_id": "c1", "__campaign_id": "k1"}, rng=lambda: 0.9)
            result = provider.send(OutgoingMessage(to="5511987654321", text="Oi"))
            schedule.assert_called_once()
            self.assertEqual(schedule.call_args.args[1], result.provider_message_id)

    def test_test_connection_and_template_rule(self):
        result = SandboxProvider({}).test_connection()
        self.assertTrue(result.ok)
        self.assertIn("nenhuma mensagem real", result.message)
        self.assertFalse(SANDBOX.requires_approved_template)
        self.assertFalse(SANDBOX.official)

    def test_rejects_invalid_recipient_and_empty_message(self):
        provider = SandboxProvider({"failure_rate": "0"})
        self.assertFalse(provider.send(OutgoingMessage(to="12", text="Oi")).ok)
        self.assertFalse(provider.send(OutgoingMessage(to="5511987654321", text="  ")).ok)

    def test_parse_failure_rate_bounds(self):
        self.assertEqual(parse_failure_rate("0,25"), 0.25)
        self.assertEqual(parse_failure_rate("9"), 0.5)
        self.assertEqual(parse_failure_rate("abc"), 0.05)


class ProviderCatalogTests(SimpleTestCase):
    def test_only_official_providers_and_sandbox(self):
        from apps.whatsapp.registry import PROVIDERS

        self.assertEqual([p.key for p in PROVIDERS], ["META_CLOUD", "DIALOG360", "TWILIO", "SANDBOX"])
        self.assertEqual({p.key for p in PROVIDERS if p.official}, {"META_CLOUD", "DIALOG360", "TWILIO"})
        for p in PROVIDERS:
            self.assertTrue(p.setup_steps)
            self.assertTrue(callable(p.create) and callable(p.parse_webhook))
        self.assertTrue(META_CLOUD.requires_approved_template and TWILIO.requires_approved_template and DIALOG360.requires_approved_template)

    def test_secret_fields_are_declared(self):
        secrets = {(p.key, f.name) for p in (META_CLOUD, TWILIO, DIALOG360) for f in p.fields if f.secret}
        self.assertEqual(secrets, {("META_CLOUD", "access_token"), ("META_CLOUD", "app_secret"), ("TWILIO", "auth_token"), ("DIALOG360", "api_key")})


# ------------------------------------------------------------------------------------------------ Credenciais


class CredentialValidationTests(SimpleTestCase):
    def field(self, provider, name):
        definition = {"META_CLOUD": META_CLOUD, "TWILIO": TWILIO, "SANDBOX": SANDBOX, "DIALOG360": DIALOG360}[provider]
        return next(f for f in definition.fields if f.name == name)

    def test_valid_values_are_normalized(self):
        self.assertEqual(validate_credential("META_CLOUD", self.field("META_CLOUD", "api_version"), "21.0"), "v21.0")
        self.assertEqual(validate_credential("TWILIO", self.field("TWILIO", "from_number"), "whatsapp:+55 (11) 99999-0000"), "+5511999990000")
        self.assertEqual(validate_credential("SANDBOX", self.field("SANDBOX", "failure_rate"), "0,1"), "0.1")
        self.assertEqual(validate_credential("DIALOG360", self.field("DIALOG360", "base_url"), "https://waba-v2.360dialog.io/"), "https://waba-v2.360dialog.io")

    def test_invalid_values_raise(self):
        cases = [
            ("META_CLOUD", "phone_number_id", "abc"),
            ("META_CLOUD", "access_token", "token com espaço 123456789"),
            ("META_CLOUD", "access_token", "curto"),
            ("META_CLOUD", "api_version", "latest"),
            ("TWILIO", "account_sid", "XX123"),
            ("TWILIO", "from_number", "123"),
            ("SANDBOX", "failure_rate", "0.9"),
            ("DIALOG360", "base_url", "https://evil.test"),
        ]
        for provider, name, value in cases:
            with self.assertRaises(CredentialError, msg=(provider, name, value)):
                validate_credential(provider, self.field(provider, name), value)

    def test_split_credentials_masks_secrets(self):
        values, masked = split_credentials(META_CLOUD.fields, {"phone_number_id": "123456789012345", "access_token": "EAAGsegredo1234567890XYZ"})
        self.assertEqual(values, {"phone_number_id": "123456789012345"})
        self.assertEqual(list(masked), ["access_token"])
        self.assertNotIn("segredo", masked["access_token"])


# ------------------------------------------------------------------------------------------------ Regras (status, opt-out, telefones)


class StatusRuleTests(SimpleTestCase):
    def test_status_only_moves_forward(self):
        self.assertEqual(next_message_status("SENT", "DELIVERED"), "DELIVERED")
        self.assertEqual(next_message_status("DELIVERED", "READ"), "READ")
        self.assertEqual(next_message_status("SENDING", "SENT"), "SENT")
        self.assertIsNone(next_message_status("READ", "DELIVERED"))
        self.assertIsNone(next_message_status("READ", "SENT"))
        self.assertIsNone(next_message_status("DELIVERED", "DELIVERED"))
        self.assertIsNone(next_message_status("DELIVERED", "SENT"))

    def test_failed_only_when_not_delivered_or_read(self):
        self.assertEqual(next_message_status("SENT", "FAILED"), "FAILED")
        self.assertEqual(next_message_status("PENDING", "FAILED"), "FAILED")
        self.assertIsNone(next_message_status("DELIVERED", "FAILED"))
        self.assertIsNone(next_message_status("READ", "FAILED"))
        self.assertIsNone(next_message_status("FAILED", "FAILED"))

    def test_delivery_confirmation_overrides_earlier_failure(self):
        self.assertEqual(next_message_status("FAILED", "DELIVERED"), "DELIVERED")
        self.assertIsNone(next_message_status("FAILED", "SENT"))

    def test_skipped_never_changes_and_unknown_is_ignored(self):
        for incoming in ("SENT", "DELIVERED", "READ", "FAILED"):
            self.assertIsNone(next_message_status("SKIPPED", incoming))
        self.assertIsNone(next_message_status("SENT", "BANANA"))

    def test_build_status_update_fills_timestamps(self):
        row = {"status": "SENT", "sent_at": None, "delivered_at": None, "read_at": None}
        update = build_status_update(row, "READ")
        self.assertEqual(update["status"], "READ")
        self.assertTrue(update["sent_at"] and update["delivered_at"] and update["read_at"])
        failed = build_status_update(row, "FAILED", error="x" * 500)
        self.assertEqual(len(failed["error"]), 300)
        self.assertIsNone(build_status_update({**row, "status": "READ"}, "DELIVERED"))


class OptOutRuleTests(SimpleTestCase):
    def test_keywords_match_after_normalization(self):
        for text in ("SAIR", "sair", "  Sair!  ", "Parar.", "stop", "CANCELAR", "descadastrar", "Remover", "DESCADASTRÁR", "Parar promoções", "sair 🙏"):
            self.assertTrue(is_opt_out_message(text), text)

    def test_other_messages_do_not_match(self):
        for text in ("", None, "   ", "Quero sair da lista de ontem", "não quero parar", "Oi", "Obrigado!", "saia"):
            self.assertFalse(is_opt_out_message(text), text)

    def test_normalizer_removes_accents_punctuation_and_extra_spaces(self):
        self.assertEqual(normalize_opt_out_text("  Não   Quero!! "), "NAO QUERO")


class InboundPhoneTests(SimpleTestCase):
    def test_candidates_include_ninth_digit_variants(self):
        # sem nono dígito → também tenta com o nono dígito (e vice-versa)
        self.assertIn("5511987654321", inbound_phone_candidates("551187654321"))
        self.assertIn("551187654321", inbound_phone_candidates("5511987654321"))
        self.assertEqual(inbound_phone_candidates("+55 (11) 98765-4321")[0], "5511987654321")

    def test_empty_input(self):
        self.assertEqual(inbound_phone_candidates(""), [])
        self.assertEqual(inbound_phone_candidates(None), [])
        self.assertEqual(inbound_phone_candidates("abc"), [])
