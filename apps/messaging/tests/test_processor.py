"""Fila de disparos: materialização, envio com limite por minuto, consentimento no envio, repetições, pausa e
cancelamento, contadores e recuperação. O provedor é sempre simulado."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from apps.auditlog.models import AuditLog
from apps.core.constants import BroadcastStatus, CampaignStatus, ConnectionStatus, MessageStatus
from apps.messaging import processor
from apps.messaging.counters import refresh_broadcast_counters
from apps.messaging.models import Broadcast, BroadcastMessage
from apps.whatsapp.types import SendResult

from .helpers import (
    FakeProvider,
    MessagingTestCase,
    make_broadcast,
    make_connection,
    make_message,
    make_template,
    make_user,
    make_voter,
)

PROVIDER = "apps.whatsapp.registry.provider_for_connection"


def refresh(obj):
    obj.refresh_from_db()
    return obj


class MaterializationTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.conn = make_connection(self.a)
        self.template = make_template(self.a, self.admin)

    def broadcast(self, creator, **extra):
        return make_broadcast(self.a, creator, self.template, self.conn, **extra)

    def test_only_consented_voters_in_creator_scope(self):
        mine = make_voter(self.a, self.coord1, name="Maria da Silva")
        of_cabo = make_voter(self.a, self.cabo1)
        other_network = make_voter(self.a, self.cabo2)
        no_consent = make_voter(self.a, self.coord1, consent=False)
        opted_out = make_voter(self.a, self.coord1, opt_out_at=timezone.now())
        no_opt_in = make_voter(self.a, self.coord1, whatsapp_opt_in=False)
        foreign = make_voter(self.b, self.admin_b)

        broadcast = self.broadcast(self.coord1)
        result = processor.materialize_broadcast(broadcast)

        self.assertEqual(result.status, BroadcastStatus.RUNNING)
        self.assertEqual(result.recipients, 2)
        broadcast = refresh(broadcast)
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)
        self.assertEqual(broadcast.total_recipients, 2)
        self.assertIsNotNone(broadcast.started_at)
        voters = set(BroadcastMessage.objects.filter(broadcast=broadcast).values_list("voter_id", flat=True))
        self.assertEqual(voters, {mine.pk, of_cabo.pk})
        for excluded in (other_network, no_consent, opted_out, no_opt_in, foreign):
            self.assertNotIn(excluded.pk, voters)
        message = BroadcastMessage.objects.get(voter=mine)
        self.assertEqual(message.status, MessageStatus.PENDING)
        self.assertEqual(message.campaign_id, self.a.pk)
        self.assertEqual(message.phone, mine.phone)
        # variáveis renderizadas por eleitor
        self.assertTrue(message.rendered_body.startswith("Olá, Maria! Aqui é Alfa."))

    def test_messageable_filter_is_always_forced(self):
        consented = make_voter(self.a, self.cabo1)
        make_voter(self.a, self.cabo1, consent=False)
        broadcast = self.broadcast(self.admin, filters={"messageable": False})
        processor.materialize_broadcast(broadcast)
        self.assertEqual(list(BroadcastMessage.objects.filter(broadcast=broadcast).values_list("voter_id", flat=True)), [consented.pk])

    def test_filters_narrow_the_audience(self):
        centro = make_voter(self.a, self.cabo1, neighborhood="Centro")
        make_voter(self.a, self.cabo1, neighborhood="Cambuí")
        broadcast = self.broadcast(self.admin, filters={"neighborhoods": ["Centro"]})
        processor.materialize_broadcast(broadcast)
        self.assertEqual(list(BroadcastMessage.objects.filter(broadcast=broadcast).values_list("voter_id", flat=True)), [centro.pk])

    def test_filter_cannot_widen_scope_to_another_network(self):
        make_voter(self.a, self.cabo2)
        broadcast = self.broadcast(self.cabo1, filters={"registered_by_ids": [str(self.cabo2.pk)]})
        result = processor.materialize_broadcast(broadcast)
        self.assertEqual(result.status, BroadcastStatus.COMPLETED)
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=broadcast).count(), 0)

    def test_no_recipients_completes(self):
        broadcast = self.broadcast(self.admin)
        result = processor.materialize_broadcast(broadcast)
        self.assertEqual((result.status, result.recipients), (BroadcastStatus.COMPLETED, 0))
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.COMPLETED)
        self.assertIsNotNone(broadcast.finished_at)

    def test_inactive_creator_fails_with_audit_row(self):
        make_voter(self.a, self.cabo1)
        creator = make_user(self.a, "gone@a.com", "COORDENADOR", parent=self.admin, is_active=False)
        broadcast = self.broadcast(creator)
        result = processor.materialize_broadcast(broadcast)
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.FAILED)
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=broadcast).count(), 0)
        row = AuditLog.objects.get(action="broadcast.fail", entity_id=str(broadcast.pk))
        self.assertTrue(row.details["automatic"])

    def test_deleted_template_and_invalid_filters_fail(self):
        make_voter(self.a, self.cabo1)
        orphan = self.broadcast(self.admin)
        self.template.delete()
        self.assertEqual(processor.materialize_broadcast(orphan).status, "FAILED")

        template = make_template(self.a, self.admin)
        bad = make_broadcast(self.a, self.admin, template, self.conn, filters={"age_min": 999})
        self.assertEqual(processor.materialize_broadcast(bad).status, "FAILED")
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=bad).count(), 0)

    def test_second_materialization_is_skipped(self):
        make_voter(self.a, self.cabo1)
        broadcast = self.broadcast(self.admin)
        self.assertEqual(processor.materialize_broadcast(broadcast).status, BroadcastStatus.RUNNING)
        self.assertEqual(processor.materialize_broadcast(broadcast).status, "SKIPPED")
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=broadcast).count(), 1)

    def test_future_broadcast_is_not_started_by_tick(self):
        make_voter(self.a, self.cabo1)
        broadcast = self.broadcast(self.admin, scheduled_at=timezone.now() + timedelta(hours=1))
        report = processor.run_queue_tick()
        self.assertEqual(report["materialized"], 0)
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.SCHEDULED)

    def test_suspended_campaign_is_not_started(self):
        make_voter(self.a, self.cabo1)
        broadcast = self.broadcast(self.admin)
        self.a.status = CampaignStatus.SUSPENDED
        self.a.save(update_fields=["status"])
        self.assertEqual(processor.run_queue_tick()["materialized"], 0)
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.SCHEDULED)


class SendingTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.conn = make_connection(self.a, rate=60)
        self.template = make_template(self.a, self.admin)
        self.voters = [make_voter(self.a, self.cabo1) for _ in range(8)]

    def running(self, **extra):
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, **extra)
        processor.materialize_broadcast(broadcast)
        return refresh(broadcast)

    def tick(self, provider=None, **kwargs):
        provider = provider or FakeProvider()
        with mock.patch(PROVIDER, return_value=provider):
            report = processor.run_queue_tick(**kwargs)
        return report, provider

    def test_tick_sends_marks_sent_and_completes(self):
        broadcast = self.running(rate_per_minute=20)
        report, provider = self.tick()
        self.assertEqual(report["sent"], 8)
        self.assertEqual(len(provider.sent), 8)
        self.assertEqual(
            set(BroadcastMessage.objects.filter(broadcast=broadcast).values_list("status", flat=True)), {MessageStatus.SENT}
        )
        message = BroadcastMessage.objects.filter(broadcast=broadcast).first()
        self.assertTrue(message.provider_message_id.startswith("wamid."))
        self.assertIsNotNone(message.sent_at)
        self.assertEqual(message.attempts, 1)
        broadcast = refresh(broadcast)
        self.assertEqual((broadcast.sent_count, broadcast.failed_count), (8, 0))
        self.assertEqual(broadcast.status, BroadcastStatus.COMPLETED)
        self.assertIsNotNone(broadcast.finished_at)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(set(report), {"materialized", "sent", "failed", "skipped", "completed", "geocoded"})

    def test_broadcast_rate_limits_each_minute(self):
        broadcast = self.running(rate_per_minute=3)
        report, provider = self.tick()
        self.assertEqual(report["sent"], 3)
        # segundo ciclo logo em seguida: a janela de 60 s ainda está cheia
        report, _ = self.tick(provider=provider)
        self.assertEqual(report["sent"], 0)
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.RUNNING)
        # um minuto depois libera mais três
        later = timezone.now() + timedelta(seconds=61)
        report, _ = self.tick(provider=provider, now=later)
        self.assertEqual(report["sent"], 3)

    def test_connection_rate_is_shared_by_all_broadcasts(self):
        self.conn.rate_per_minute = 5
        self.conn.save(update_fields=["rate_per_minute"])
        first = self.running(rate_per_minute=5)
        second = self.running(rate_per_minute=5)
        report, provider = self.tick()
        self.assertEqual(report["sent"], 5)
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=first, status=MessageStatus.SENT).count(), 5)
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=second, status=MessageStatus.SENT).count(), 0)

    def test_max_messages_caps_the_tick(self):
        self.running(rate_per_minute=60)
        report, _ = self.tick(max_messages=2)
        self.assertEqual(report["sent"], 2)

    def test_campaign_scoped_tick_ignores_other_campaigns(self):
        other_conn = make_connection(self.b, rate=60)
        other_template = make_template(self.b, self.admin_b)
        make_voter(self.b, self.admin_b)
        other = make_broadcast(self.b, self.admin_b, other_template, other_conn)
        processor.materialize_broadcast(other)
        mine = self.running()
        report, _ = self.tick(campaign_id=self.a.pk)
        self.assertEqual(report["sent"], 8)
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=other, status=MessageStatus.SENT).count(), 0)
        self.assertEqual(refresh(mine).status, BroadcastStatus.COMPLETED)
        self.geocode.assert_not_called()  # geocodificação só no ciclo global

    def test_global_tick_runs_geocoding(self):
        self.tick()
        self.geocode.assert_called_once_with(5)

    def test_voter_opted_out_after_materialization_is_skipped(self):
        broadcast = self.running(rate_per_minute=20)
        leaving, other = self.voters[0], self.voters[1]
        leaving.opt_out_at = timezone.now()
        leaving.save(update_fields=["opt_out_at"])
        other.whatsapp_opt_in = False
        other.save(update_fields=["whatsapp_opt_in"])
        report, provider = self.tick()
        self.assertEqual(report["skipped"], 2)
        self.assertEqual(report["sent"], 6)
        self.assertNotIn(leaving.phone, [m.to for m in provider.sent])
        self.assertNotIn(other.phone, [m.to for m in provider.sent])
        skipped = BroadcastMessage.objects.get(broadcast=broadcast, voter=leaving)
        self.assertEqual(skipped.status, MessageStatus.SKIPPED)
        self.assertIn("descadastro", skipped.error)
        self.assertIsNone(skipped.sent_at)

    def test_deleted_voter_is_skipped(self):
        broadcast = self.running()
        self.voters[0].delete()
        report, _ = self.tick()
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=broadcast, status=MessageStatus.SKIPPED).count(), 1)

    def test_retryable_error_goes_back_to_queue_then_fails_after_three_attempts(self):
        BroadcastMessage.objects.all().delete()
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.RUNNING)
        message = make_message(broadcast, self.voters[0])
        provider = FakeProvider([SendResult(ok=False, error="limite", retryable=True)] * 3)
        for expected_status, expected_attempts in (
            (MessageStatus.PENDING, 1),
            (MessageStatus.PENDING, 2),
            (MessageStatus.FAILED, 3),
        ):
            self.tick(provider=provider, now=timezone.now() + timedelta(minutes=expected_attempts * 2))
            message = refresh(message)
            self.assertEqual((message.status, message.attempts), (expected_status, expected_attempts))
        self.assertEqual(message.error, "limite")
        broadcast = refresh(broadcast)
        self.assertEqual(broadcast.failed_count, 1)
        self.assertEqual(broadcast.status, BroadcastStatus.COMPLETED)

    def test_permanent_error_fails_immediately(self):
        BroadcastMessage.objects.all().delete()
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.RUNNING)
        message = make_message(broadcast, self.voters[0])
        report, _ = self.tick(provider=FakeProvider([SendResult(ok=False, error="número inválido", retryable=False)]))
        message = refresh(message)
        self.assertEqual((message.status, message.attempts, report["failed"]), (MessageStatus.FAILED, 1, 1))
        self.assertEqual(message.error, "número inválido")

    def test_provider_exception_is_treated_as_temporary_failure(self):
        BroadcastMessage.objects.all().delete()
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.RUNNING)
        message = make_message(broadcast, self.voters[0])
        self.tick(provider=FakeProvider([RuntimeError("token secreto xyz")]))
        message = refresh(message)
        self.assertEqual(message.status, MessageStatus.PENDING)
        self.assertNotIn("secreto", message.error)  # só o tipo do erro, nunca a mensagem

    def test_paused_broadcast_sends_nothing(self):
        broadcast = self.running()
        Broadcast.objects.filter(pk=broadcast.pk).update(status=BroadcastStatus.PAUSED)
        report, provider = self.tick()
        self.assertEqual((report["sent"], len(provider.sent)), (0, 0))
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=broadcast, status=MessageStatus.PENDING).count(), 8)
        # retomar volta a enviar
        Broadcast.objects.filter(pk=broadcast.pk).update(status=BroadcastStatus.RUNNING)
        self.assertEqual(self.tick()[0]["sent"], 8)

    def test_cancelled_broadcast_skips_pending_messages(self):
        broadcast = self.running()
        Broadcast.objects.filter(pk=broadcast.pk).update(status=BroadcastStatus.CANCELLED)
        report, provider = self.tick()
        self.assertEqual(report["skipped"], 8)
        self.assertEqual(len(provider.sent), 0)
        row = BroadcastMessage.objects.filter(broadcast=broadcast).first()
        self.assertEqual((row.status, row.error), (MessageStatus.SKIPPED, "Cancelado"))
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.CANCELLED)  # contadores não "descancelam"

    def test_disconnected_connection_pauses_with_audit(self):
        broadcast = self.running()
        self.conn.status = ConnectionStatus.ERROR
        self.conn.save(update_fields=["status"])
        report, provider = self.tick()
        self.assertEqual((report["sent"], len(provider.sent)), (0, 0))
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.PAUSED)
        row = AuditLog.objects.get(action="broadcast.pause", entity_id=str(broadcast.pk))
        self.assertTrue(row.details["automatic"])
        self.assertIn("conexão", row.details["reason"].lower())

    def test_deleted_connection_pauses(self):
        broadcast = self.running()
        self.conn.delete()
        self.tick()
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.PAUSED)

    def test_connection_of_another_campaign_is_never_used(self):
        foreign = make_connection(self.b)
        broadcast = self.running()
        Broadcast.objects.filter(pk=broadcast.pk).update(connection=foreign)
        report, provider = self.tick()
        self.assertEqual((report["sent"], len(provider.sent)), (0, 0))
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.PAUSED)

    def test_unreadable_credentials_pause_the_broadcast(self):
        broadcast = self.running()
        with mock.patch(PROVIDER, side_effect=ValueError("chave errada")):
            processor.run_queue_tick()
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.PAUSED)

    def test_stuck_sending_messages_return_to_queue(self):
        BroadcastMessage.objects.all().delete()
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.PAUSED)
        stuck = make_message(broadcast, self.voters[0], status=MessageStatus.SENDING, attempts=1)
        exhausted = make_message(broadcast, self.voters[1], status=MessageStatus.SENDING, attempts=3)
        fresh = make_message(broadcast, self.voters[2], status=MessageStatus.SENDING, attempts=1)
        old = timezone.now() - timedelta(minutes=10)
        BroadcastMessage.objects.filter(pk__in=[stuck.pk, exhausted.pk]).update(updated_at=old)
        self.tick()
        self.assertEqual(refresh(stuck).status, MessageStatus.PENDING)
        self.assertEqual(refresh(exhausted).status, MessageStatus.FAILED)
        self.assertEqual(refresh(fresh).status, MessageStatus.SENDING)

    def test_official_provider_receives_approved_template_with_mapped_parameters(self):
        official = make_connection(self.a, provider="META_CLOUD", rate=60, default=False)
        template = make_template(
            self.a,
            self.admin,
            provider_template_name="convite_evento",
            provider_template_language="pt_BR",
            provider_variables=["primeiro_nome", "bairro", "candidato"],
        )
        BroadcastMessage.objects.all().delete()
        voter = make_voter(self.a, self.cabo1, name="João Pereira", neighborhood="Vila Nova")
        broadcast = make_broadcast(self.a, self.admin, template, official, status=BroadcastStatus.RUNNING)
        make_message(broadcast, voter, rendered_body="Olá João")
        _, provider = self.tick()
        (sent,) = provider.sent
        self.assertEqual(sent.to, voter.phone)
        self.assertEqual(sent.text, "Olá João")
        self.assertEqual(sent.template.name, "convite_evento")
        self.assertEqual(sent.template.language, "pt_BR")
        self.assertEqual(sent.template.parameters, ["João", "Vila Nova", "Alfa"])

    def test_official_provider_without_approved_template_name_pauses(self):
        official = make_connection(self.a, provider="TWILIO", rate=60, default=False)
        broadcast = make_broadcast(self.a, self.admin, self.template, official, status=BroadcastStatus.RUNNING)
        make_message(broadcast, self.voters[0])
        _, provider = self.tick()
        self.assertEqual(len(provider.sent), 0)
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.PAUSED)

    def test_sandbox_provider_gets_plain_text_and_media(self):
        template = make_template(self.a, self.admin, type="IMAGE", media_url="https://exemplo.com.br/foto.jpg", provider_template_name="x")
        BroadcastMessage.objects.all().delete()
        broadcast = make_broadcast(self.a, self.admin, template, self.conn, status=BroadcastStatus.RUNNING)
        make_message(broadcast, self.voters[0], rendered_body="Veja a foto")
        _, provider = self.tick()
        (sent,) = provider.sent
        self.assertIsNone(sent.template)
        self.assertEqual((sent.media.type, sent.media.url), ("IMAGE", "https://exemplo.com.br/foto.jpg"))


class CountersTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.conn = make_connection(self.a)
        self.template = make_template(self.a, self.admin)

    def messages(self, broadcast, statuses):
        for status in statuses:
            make_message(broadcast, make_voter(self.a, self.cabo1), status=status)

    def test_aggregation_of_status_counts(self):
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.PAUSED)
        self.messages(
            broadcast,
            ["SENT", "SENT", "DELIVERED", "READ", "READ", "FAILED", "SKIPPED", "PENDING"],
        )
        refresh_broadcast_counters(broadcast.pk)
        broadcast = refresh(broadcast)
        self.assertEqual(broadcast.sent_count, 5)  # SENT + DELIVERED + READ
        self.assertEqual(broadcast.delivered_count, 3)  # DELIVERED + READ
        self.assertEqual(broadcast.read_count, 2)
        self.assertEqual(broadcast.failed_count, 1)
        self.assertEqual(broadcast.status, BroadcastStatus.PAUSED)  # não conclui pausado

    def test_running_without_queue_completes(self):
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.RUNNING)
        self.messages(broadcast, ["SENT", "DELIVERED", "FAILED"])
        refresh_broadcast_counters(broadcast.pk)
        broadcast = refresh(broadcast)
        self.assertEqual(broadcast.status, BroadcastStatus.COMPLETED)
        self.assertIsNotNone(broadcast.finished_at)

    def test_running_with_pending_or_sending_stays_running(self):
        for status in ("PENDING", "SENDING"):
            broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.RUNNING)
            self.messages(broadcast, ["SENT", status])
            refresh_broadcast_counters(broadcast.pk)
            self.assertEqual(refresh(broadcast).status, BroadcastStatus.RUNNING)

    def test_cancelled_is_not_overwritten(self):
        broadcast = make_broadcast(self.a, self.admin, self.template, self.conn, status=BroadcastStatus.CANCELLED)
        self.messages(broadcast, ["SENT"])
        refresh_broadcast_counters(broadcast.pk)
        broadcast = refresh(broadcast)
        self.assertEqual((broadcast.status, broadcast.sent_count), (BroadcastStatus.CANCELLED, 1))

    def test_unknown_broadcast_is_ignored(self):
        import uuid

        refresh_broadcast_counters(uuid.uuid4())


class WorkerCommandTests(MessagingTestCase):
    def test_once_runs_a_single_tick(self):
        conn = make_connection(self.a)
        template = make_template(self.a, self.admin)
        make_voter(self.a, self.cabo1)
        broadcast = make_broadcast(self.a, self.admin, template, conn)
        out = StringIO()
        with mock.patch(PROVIDER, return_value=FakeProvider()):
            call_command("run_worker", "--once", stdout=out)
        self.assertEqual(refresh(broadcast).status, BroadcastStatus.COMPLETED)
        self.assertIn("1 enviada(s)", out.getvalue())
        self.assertNotIn("55119", out.getvalue())  # nenhum telefone no log

    def test_bad_tick_does_not_crash_the_worker(self):
        out = StringIO()
        with mock.patch("apps.messaging.management.commands.run_worker.run_queue_tick", side_effect=RuntimeError("boom")):
            call_command("run_worker", "--once", stdout=out)
        self.assertEqual(out.getvalue(), "")
