"""Lógica pura do módulo (sem banco): orçamento de envio, contadores, máquina de estados, parâmetros do template
oficial, formatação do WhatsApp, agendamento e instrução de descadastro."""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from apps.core.constants import BroadcastStatus
from apps.messaging import logic
from apps.messaging.whatsapp_format import (
    format_whatsapp_html,
    nodes_to_plain_text,
    parse_whatsapp_formatting,
    plain_excerpt,
)
from apps.whatsapp.types import TemplateCall


class SendBudgetTests(SimpleTestCase):
    def budget(self, **kw):
        base = dict(
            connection_rate=60, connection_sent_last_minute=0, broadcast_rate=20, broadcast_sent_last_minute=0, tick_remaining=200
        )
        base.update(kw)
        return logic.compute_send_budget(**base)

    def test_limited_by_broadcast_rate(self):
        self.assertEqual(self.budget(), 20)

    def test_limited_by_connection_remaining(self):
        # a conexão já enviou 55 de 60 no último minuto (talvez por outro disparo)
        self.assertEqual(self.budget(connection_sent_last_minute=55), 5)

    def test_limited_by_own_recent_sends(self):
        self.assertEqual(self.budget(broadcast_sent_last_minute=15), 5)

    def test_broadcast_rate_is_capped_by_connection_rate(self):
        self.assertEqual(self.budget(connection_rate=10, broadcast_rate=100), 10)

    def test_limited_by_tick_remaining(self):
        self.assertEqual(self.budget(tick_remaining=3), 3)

    def test_never_negative(self):
        self.assertEqual(self.budget(connection_sent_last_minute=999, broadcast_sent_last_minute=999, tick_remaining=-5), 0)


class CountersTests(SimpleTestCase):
    def test_aggregation(self):
        c = logic.counters_from_groups(
            {"PENDING": 4, "SENDING": 1, "SENT": 3, "DELIVERED": 2, "READ": 1, "FAILED": 2, "SKIPPED": 5}
        )
        self.assertEqual(c.total, 18)
        self.assertEqual(c.queued, 5)
        self.assertEqual(c.sent, 6)  # SENT + DELIVERED + READ
        self.assertEqual(c.delivered, 3)  # DELIVERED + READ
        self.assertEqual(c.read, 1)
        self.assertEqual(c.failed, 2)
        self.assertEqual(c.skipped, 5)
        self.assertEqual(c.processed, 13)  # enviadas + falhas + ignoradas

    def test_accepts_pairs_and_empty(self):
        self.assertEqual(logic.counters_from_groups([("SENT", 2), ("SENT", 1)]).sent, 3)
        self.assertEqual(logic.counters_from_groups({}).total, 0)

    def test_completion_rule(self):
        self.assertTrue(logic.should_complete("RUNNING", 0, 0))
        self.assertFalse(logic.should_complete("RUNNING", 1, 0))
        self.assertFalse(logic.should_complete("RUNNING", 0, 1))
        self.assertFalse(logic.should_complete("PAUSED", 0, 0))
        self.assertFalse(logic.should_complete("CANCELLED", 0, 0))

    def test_rates_and_percent(self):
        self.assertEqual(logic.percent(1, 0), 0.0)
        self.assertEqual(logic.percent(1, 4), 25.0)
        self.assertEqual(logic.percent(9, 4), 100.0)
        self.assertEqual(logic.broadcast_rates(10, 5, 1), (50.0, 20.0))
        self.assertEqual(logic.broadcast_rates(0, 0, 0), (0.0, 0.0))


class StateMachineTests(SimpleTestCase):
    def test_transitions(self):
        S = BroadcastStatus
        self.assertEqual(logic.next_broadcast_status(S.RUNNING, "pause"), S.PAUSED)
        self.assertEqual(logic.next_broadcast_status(S.PAUSED, "resume"), S.RUNNING)
        for status in (S.SCHEDULED, S.RUNNING, S.PAUSED):
            self.assertEqual(logic.next_broadcast_status(status, "cancel"), S.CANCELLED)
        self.assertEqual(logic.next_broadcast_status(S.COMPLETED, "retry"), S.RUNNING)
        self.assertEqual(logic.next_broadcast_status(S.RUNNING, "retry"), S.RUNNING)

    def test_invalid_transitions(self):
        S = BroadcastStatus
        self.assertIsNone(logic.next_broadcast_status(S.SCHEDULED, "pause"))
        self.assertIsNone(logic.next_broadcast_status(S.RUNNING, "resume"))
        self.assertIsNone(logic.next_broadcast_status(S.COMPLETED, "cancel"))
        self.assertIsNone(logic.next_broadcast_status(S.CANCELLED, "resume"))
        self.assertIsNone(logic.next_broadcast_status(S.PAUSED, "retry"))
        self.assertIsNone(logic.next_broadcast_status(S.RUNNING, "inexistente"))

    def test_delete_blocked_only_while_running(self):
        self.assertFalse(logic.can_delete_broadcast(BroadcastStatus.RUNNING))
        for status in (BroadcastStatus.PAUSED, BroadcastStatus.COMPLETED, BroadcastStatus.SCHEDULED, BroadcastStatus.CANCELLED):
            self.assertTrue(logic.can_delete_broadcast(status))

    def test_available_actions_follow_status_and_permissions(self):
        running = logic.available_actions("RUNNING", retryable_failures=2, can_edit=True, can_delete=True)
        self.assertEqual(
            running, {"pause": True, "resume": False, "cancel": True, "retry": True, "delete": False}
        )
        paused = logic.available_actions("PAUSED", retryable_failures=0, can_edit=True, can_delete=True)
        self.assertTrue(paused["resume"] and paused["cancel"] and paused["delete"])
        self.assertFalse(paused["pause"] or paused["retry"])
        readonly = logic.available_actions("RUNNING", retryable_failures=3, can_edit=False, can_delete=False)
        self.assertFalse(any(readonly.values()))
        done = logic.available_actions("COMPLETED", retryable_failures=1, can_edit=True, can_delete=True)
        self.assertTrue(done["retry"] and done["delete"])
        self.assertFalse(done["cancel"])


class OfficialTemplateTests(SimpleTestCase):
    context = {"primeiro_nome": "Maria", "bairro": "Centro", "candidato": "Dr. João", "cidade": ""}

    def test_parameters_follow_configured_order(self):
        self.assertEqual(
            logic.map_template_parameters(["candidato", "primeiro_nome", "bairro"], self.context),
            ["Dr. João", "Maria", "Centro"],
        )

    def test_empty_values_become_dash_and_whitespace_is_cleaned(self):
        ctx = {"bairro": "Vila\n  Nova\tAlta", "cidade": "   "}
        self.assertEqual(logic.map_template_parameters(["bairro", "cidade", "cabo"], ctx), ["Vila Nova Alta", "-", "-"])

    def test_unknown_keys_and_bad_types_are_ignored(self):
        self.assertEqual(logic.map_template_parameters(["nao_existe", "bairro", 7], self.context), ["Centro"])
        self.assertEqual(logic.map_template_parameters(None, self.context), [])
        self.assertEqual(logic.map_template_parameters("bairro", self.context), [])

    def test_outgoing_message_uses_template_call_only_when_required(self):
        class Tpl:
            type = "TEXT"
            media_url = ""
            provider_template_name = "convite_evento"
            provider_template_language = "pt_BR"
            provider_variables = ["primeiro_nome", "bairro"]

        official = logic.build_outgoing_message(
            to="5511999990000", rendered_body="Olá Maria", template=Tpl(), requires_approved_template=True, context=self.context
        )
        self.assertEqual(official.text, "Olá Maria")
        self.assertEqual(official.template, TemplateCall(name="convite_evento", language="pt_BR", parameters=["Maria", "Centro"]))
        sandbox = logic.build_outgoing_message(
            to="5511999990000", rendered_body="Olá Maria", template=Tpl(), requires_approved_template=False, context=self.context
        )
        self.assertIsNone(sandbox.template)

    def test_media_requires_https(self):
        class Tpl:
            type = "DOCUMENT"
            provider_template_name = ""
            provider_variables = None

        Tpl.media_url = "https://exemplo.com.br/arquivos/Plano%20de%20Governo.pdf"
        media = logic.media_for_template(Tpl)
        self.assertEqual((media.type, media.filename), ("DOCUMENT", "Plano de Governo.pdf"))
        Tpl.media_url = "http://exemplo.com.br/a.pdf"
        self.assertIsNone(logic.media_for_template(Tpl))
        Tpl.type = "TEXT"
        Tpl.media_url = "https://exemplo.com.br/a.pdf"
        self.assertIsNone(logic.media_for_template(Tpl))

    def test_provider_template_name_pattern(self):
        for ok in ("convite_evento", "hello_world", "HX" + "a" * 32):
            self.assertTrue(logic.PROVIDER_TEMPLATE_NAME_RE.match(ok), ok)
        for bad in ("Convite Evento", "com-hifen", "", "HXshort"):
            self.assertFalse(logic.PROVIDER_TEMPLATE_NAME_RE.match(bad), bad)


class SendBlockerTests(SimpleTestCase):
    class Conn:
        campaign_id = 1
        status = "CONNECTED"

    class Tpl:
        provider_template_name = ""

    def blocker(self, **kw):
        base = dict(
            connection=self.Conn(), campaign_id=1, provider_known=True, requires_approved_template=False, template=self.Tpl()
        )
        base.update(kw)
        return logic.send_blocker(**base)

    def test_ok(self):
        self.assertIsNone(self.blocker())

    def test_blockers(self):
        self.assertEqual(self.blocker(connection=None).code, "connection_missing")
        self.assertEqual(self.blocker(campaign_id=2).code, "connection_campaign")
        offline = self.Conn()
        offline.status = "ERROR"
        self.assertEqual(self.blocker(connection=offline).code, "connection_status")
        self.assertEqual(self.blocker(provider_known=False).code, "provider_unknown")
        self.assertEqual(self.blocker(requires_approved_template=True).code, "template_required")

    def test_recipient_skip_reasons(self):
        class V:
            campaign_id = 1
            opt_out_at = None
            whatsapp_opt_in = True
            consent_at = datetime.now(timezone.utc)
            phone = "5511900000001"

        class M:
            campaign_id = 1
            phone = "5511900000001"

        self.assertIsNone(logic.recipient_skip_reason(V(), M()))
        self.assertIn("excluído", logic.recipient_skip_reason(None, M()))
        voter = V()
        voter.opt_out_at = datetime.now(timezone.utc)
        self.assertIn("descadastro", logic.recipient_skip_reason(voter, M()))
        voter = V()
        voter.whatsapp_opt_in = False
        self.assertIn("consentimento", logic.recipient_skip_reason(voter, M()))
        voter = V()
        voter.consent_at = None
        self.assertIn("consentimento", logic.recipient_skip_reason(voter, M()))
        voter = V()
        voter.phone = "5511900000002"
        self.assertIn("Telefone", logic.recipient_skip_reason(voter, M()))
        voter = V()
        voter.campaign_id = 2
        self.assertIn("outra campanha", logic.recipient_skip_reason(voter, M()))


class ScheduleTests(SimpleTestCase):
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)  # 09:00 em Brasília (UTC-3)

    def test_local_time_is_interpreted_in_sao_paulo(self):
        self.assertEqual(logic.zoned_local_to_utc("2026-10-20T14:30"), datetime(2026, 10, 20, 17, 30, tzinfo=timezone.utc))

    def test_roundtrip(self):
        value = logic.zoned_local_to_utc("2026-10-20T14:30")
        self.assertEqual(logic.to_local_input(value), "2026-10-20T14:30")

    def test_valid_future(self):
        result = logic.validate_schedule("2026-10-10T10:00", self.now)  # 13:00 UTC > 12:00 UTC
        self.assertTrue(result.ok)
        self.assertEqual(result.date, datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc))

    def test_past_is_rejected(self):
        result = logic.validate_schedule("2026-10-10T08:59", self.now)
        self.assertFalse(result.ok)
        self.assertIn("futuro", result.error)

    def test_invalid_or_empty(self):
        for value in (None, "", "   ", "amanhã", "2026-02-31T10:00", "2026-13-01T10:00", "10/10/2026 10:00"):
            self.assertFalse(logic.validate_schedule(value, self.now).ok, value)

    def test_too_far_ahead(self):
        far = (self.now + timedelta(days=logic.MAX_SCHEDULE_DAYS + 5)).astimezone(logic.CAMPAIGN_TZ).strftime("%Y-%m-%dT%H:%M")
        self.assertFalse(logic.validate_schedule(far, self.now).ok)

    def test_duration_estimate_and_format(self):
        self.assertEqual(logic.estimate_duration_minutes(0, 20), 0)
        self.assertEqual(logic.estimate_duration_minutes(100, 20), 5)
        self.assertEqual(logic.estimate_duration_minutes(101, 20), 6)
        self.assertEqual(logic.estimate_duration_minutes(5, 0), 5)
        self.assertEqual(logic.format_duration(0), "—")
        self.assertEqual(logic.format_duration(1), "cerca de 1 min")
        self.assertEqual(logic.format_duration(135), "cerca de 2 h 15 min")
        self.assertEqual(logic.format_duration(1500), "cerca de 1 dia e 1 h")


class OptOutTests(SimpleTestCase):
    def test_detection(self):
        self.assertTrue(logic.has_opt_out_instruction("Oi! Responda SAIR para parar."))
        self.assertTrue(logic.has_opt_out_instruction("digite sair"))
        self.assertTrue(logic.has_opt_out_instruction("Para cancelar, responda PARAR"))
        self.assertFalse(logic.has_opt_out_instruction("Venha à caminhada de sábado!"))
        self.assertFalse(logic.has_opt_out_instruction("Sairemos às 9h"))  # palavra inteira, não prefixo
        self.assertFalse(logic.has_opt_out_instruction(""))

    def test_append_instruction(self):
        out = logic.append_opt_out_instruction("Olá!  \n")
        self.assertEqual(out, "Olá!\n\n" + logic.OPT_OUT_INSTRUCTION)
        self.assertTrue(logic.has_opt_out_instruction(out))
        self.assertEqual(logic.append_opt_out_instruction(""), logic.OPT_OUT_INSTRUCTION)


class WhatsAppFormatTests(SimpleTestCase):
    def types(self, text):
        return [n["type"] for n in parse_whatsapp_formatting(text)]

    def test_bold_italic_strike(self):
        nodes = parse_whatsapp_formatting("*forte* _suave_ ~riscado~")
        self.assertEqual([n["type"] for n in nodes], ["bold", "text", "italic", "text", "strike"])
        self.assertEqual(nodes[0]["children"], [{"type": "text", "text": "forte"}])

    def test_nested(self):
        nodes = parse_whatsapp_formatting("*negrito _e itálico_*")
        self.assertEqual(nodes[0]["type"], "bold")
        self.assertEqual([c["type"] for c in nodes[0]["children"]], ["text", "italic"])

    def test_markers_inside_words_are_literal(self):
        self.assertEqual(self.types("snake_case_name"), ["text"])
        self.assertEqual(self.types("2*3*4"), ["text"])

    def test_marker_followed_by_space_is_literal(self):
        self.assertEqual(self.types("* não é negrito *"), ["text"])
        self.assertEqual(self.types("*sem fechar"), ["text"])

    def test_styles_do_not_cross_lines(self):
        self.assertNotIn("bold", self.types("*linha 1\nlinha 2*"))

    def test_line_breaks(self):
        self.assertEqual(self.types("a\nb"), ["text", "break", "text"])
        self.assertEqual(self.types("a\r\nb"), ["text", "break", "text"])

    def test_monospace(self):
        nodes = parse_whatsapp_formatting("```*literal*```")
        self.assertEqual(nodes[0]["type"], "mono")
        self.assertEqual(nodes_to_plain_text(nodes), "*literal*")

    def test_plain_text_and_excerpt(self):
        self.assertEqual(nodes_to_plain_text(parse_whatsapp_formatting("*Olá* _mundo_")), "Olá mundo")
        self.assertEqual(plain_excerpt("*Olá*\n\n  mundo"), "Olá mundo")
        self.assertTrue(plain_excerpt("a" * 500, 50).endswith("…"))
        self.assertLessEqual(len(plain_excerpt("a" * 500, 50)), 50)

    def test_html_is_escaped(self):
        html = str(format_whatsapp_html("*<script>alert(1)</script>*\n<b>x</b>"))
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>", html)
        self.assertIn("<strong>&lt;script&gt;", html)
        self.assertIn("<br>", html)
