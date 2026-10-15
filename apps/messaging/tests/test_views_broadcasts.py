"""Disparos: lista, detalhe, ações, assistente (validações), API do público e endpoint de cron."""

import json
from datetime import timedelta
from unittest import mock

from django.test import Client, override_settings
from django.utils import timezone

from apps.auditlog.models import AuditLog
from apps.core.constants import BroadcastStatus, ConnectionStatus, MessageStatus
from apps.messaging import logic
from apps.messaging.models import Broadcast, BroadcastMessage

from .helpers import (
    FakeProvider,
    MessagingTestCase,
    make_broadcast,
    make_connection,
    make_message,
    make_template,
    make_voter,
)

BASE = "/painel/mensagens/disparos/"
NEW = f"{BASE}novo/"
AUDIENCE = "/api/painel/disparos/publico/"
PROVIDER = "apps.whatsapp.registry.provider_for_connection"


class Fixtures(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.conn = make_connection(self.a, rate=60)
        self.template = make_template(self.a, self.admin, name="Convite")

    def broadcast(self, creator=None, status=BroadcastStatus.RUNNING, **extra):
        return make_broadcast(self.a, creator or self.admin, self.template, self.conn, status=status, **extra)

    def url(self, broadcast, suffix=""):
        return f"{BASE}{broadcast.pk}/{suffix}"

    def messages_in(self, flash_response):
        return " | ".join(str(m) for m in flash_response.context["messages"])


# ----------------------------------------------------------------------------------------------------- lista e detalhe


class BroadcastAccessTests(Fixtures):
    def test_anonymous_is_redirected_to_login(self):
        broadcast = self.broadcast()
        for url in (BASE, NEW, self.url(broadcast)):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/login/"), url)

    def test_pages_by_role(self):
        broadcast = self.broadcast()
        own = self.broadcast(creator=self.coord1)
        self.login(self.admin)
        for url in (BASE, NEW, self.url(broadcast), self.url(own)):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        # coordenador: pode ver a lista (padrão) mas não criar
        self.login(self.coord1)
        self.assertEqual(self.client.get(BASE).status_code, 200)
        self.assertEqual(self.client.get(self.url(own)).status_code, 200)
        self.assertEqual(self.client.get(NEW).status_code, 403)
        # cabo: sem acesso ao módulo
        self.login(self.cabo1)
        for url in (BASE, NEW, self.url(own)):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        # super admin não opera campanhas
        self.login(self.superuser)
        self.assertEqual(self.client.get(BASE).status_code, 302)

    def test_non_admin_sees_only_own_broadcasts(self):
        mine = self.broadcast(creator=self.coord1, name="Disparo do Carlos")
        others = self.broadcast(creator=self.coord2, name="Disparo da Clara")
        admins = self.broadcast(creator=self.admin, name="Disparo da Ana")
        self.login(self.coord1)
        response = self.client.get(BASE)
        self.assertContains(response, "Disparo do Carlos")
        self.assertNotContains(response, "Disparo da Clara")
        self.assertNotContains(response, "Disparo da Ana")
        self.assertEqual(self.client.get(self.url(mine)).status_code, 200)
        self.assertEqual(self.client.get(self.url(others)).status_code, 404)
        self.assertEqual(self.client.get(self.url(admins)).status_code, 404)
        # o ADMIN vê todos
        self.login(self.admin)
        self.assertEqual({b.pk for b in self.client.get(BASE).context["broadcasts"]}, {mine.pk, others.pk, admins.pk})

    def test_other_campaign_broadcast_is_404_even_for_admin(self):
        conn_b = make_connection(self.b)
        tpl_b = make_template(self.b, self.admin_b)
        foreign = make_broadcast(self.b, self.admin_b, tpl_b, conn_b, name="Disparo da outra campanha")
        self.login(self.admin)
        self.assertEqual(self.client.get(self.url(foreign)).status_code, 404)
        self.assertNotContains(self.client.get(BASE), "Disparo da outra campanha")
        for suffix in ("acao/pause/", "acao/cancel/", "excluir/", "processar/"):
            self.assertEqual(self.client.post(self.url(foreign, suffix)).status_code, 404, suffix)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, BroadcastStatus.SCHEDULED)

    def test_invalid_id_is_404(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(f"{BASE}nao-e-uuid/").status_code, 404)


class BroadcastListTests(Fixtures):
    def test_empty_state(self):
        self.login(self.admin)
        self.assertContains(self.client.get(BASE), "Nenhum disparo ainda")

    def test_rows_show_progress_and_rates(self):
        broadcast = self.broadcast(total_recipients=10)
        for status in ("SENT", "DELIVERED", "DELIVERED", "READ", "FAILED", "SKIPPED", "PENDING"):
            make_message(broadcast, make_voter(self.a, self.cabo1), status=status)
        self.login(self.admin)
        response = self.client.get(BASE)
        row = response.context["broadcasts"][0]
        self.assertEqual((row.stats.total, row.stats.processed, row.stats.sent), (7, 6, 4))
        self.assertAlmostEqual(row.progress_pct, 6 / 7 * 100)
        self.assertAlmostEqual(row.delivery_rate, 75.0)
        self.assertAlmostEqual(row.read_rate, 100 / 3)
        self.assertContains(response, "Convite")
        self.assertContains(response, "Enviando")

    def test_status_filter(self):
        self.broadcast(status=BroadcastStatus.COMPLETED, name="Concluído A")
        self.broadcast(status=BroadcastStatus.PAUSED, name="Pausado B")
        self.login(self.admin)
        response = self.client.get(BASE, {"status": "PAUSED"})
        self.assertEqual([b.name for b in response.context["broadcasts"]], ["Pausado B"])
        self.assertEqual(len(self.client.get(BASE, {"status": "XPTO"}).context["broadcasts"]), 2)

    def test_auto_refresh_only_while_active(self):
        active = self.broadcast(status=BroadcastStatus.RUNNING)
        self.login(self.admin)
        page = self.client.get(BASE)
        self.assertContains(page, 'hx-trigger="every 5s"')
        partial = self.client.get(BASE, HTTP_HX_REQUEST="true")
        self.assertNotContains(partial, "<html")
        self.assertContains(partial, 'id="broadcast-live"')
        self.assertContains(partial, 'hx-trigger="every 5s"')
        self.assertIn("HX-Request", partial["Vary"])
        Broadcast.objects.filter(pk=active.pk).update(status=BroadcastStatus.COMPLETED)
        self.assertNotContains(self.client.get(BASE, HTTP_HX_REQUEST="true"), "every 5s")

    def test_names_are_escaped(self):
        self.broadcast(name="<img src=x onerror=alert(1)>")
        self.login(self.admin)
        response = self.client.get(BASE)
        self.assertNotContains(response, "<img src=x")
        self.assertContains(response, "&lt;img src=x")


class BroadcastDetailTests(Fixtures):
    def test_detail_shows_stats_recipients_and_audience(self):
        broadcast = self.broadcast(filters={"neighborhoods": ["Centro"]}, total_recipients=4)
        voters = [make_voter(self.a, self.cabo1, name=f"Pessoa {i}") for i in range(4)]
        for voter, status in zip(voters, ("SENT", "DELIVERED", "FAILED", "PENDING")):
            make_message(broadcast, voter, status=status, error="Número inválido" if status == "FAILED" else "")
        self.login(self.admin)
        response = self.client.get(self.url(broadcast))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 4)
        self.assertEqual(response.context["stats"].failed, 1)
        self.assertEqual(response.context["audience"], [("Bairros", "Centro")])
        self.assertContains(response, "Pessoa 0")
        self.assertContains(response, "Número inválido")
        self.assertContains(response, "Processar fila agora")  # ADMIN, disparo em andamento
        self.assertContains(response, 'hx-trigger="every 5s"')
        partial = self.client.get(self.url(broadcast), HTTP_HX_REQUEST="true")
        self.assertNotContains(partial, "<html")
        self.assertContains(partial, 'id="broadcast-live"')
        self.assertContains(partial, "Pessoa 0")

    def test_status_filter_and_pagination(self):
        broadcast = self.broadcast(status=BroadcastStatus.COMPLETED)
        for i in range(120):
            make_message(broadcast, make_voter(self.a, self.cabo1), status="SENT" if i < 100 else "FAILED")
        self.login(self.admin)
        first = self.client.get(self.url(broadcast))
        self.assertEqual(len(first.context["recipients"]), 50)
        self.assertEqual(first.context["page_obj"].paginator.num_pages, 3)
        self.assertEqual(len(self.client.get(self.url(broadcast), {"page": 3}).context["recipients"]), 20)
        failed = self.client.get(self.url(broadcast), {"status": "FAILED"})
        self.assertEqual(len(failed.context["recipients"]), 20)
        self.assertNotContains(self.client.get(self.url(broadcast)), "every 5s")  # concluído: sem atualização automática

    def test_process_button_is_for_admin_only(self):
        mine = self.broadcast(creator=self.coord1)
        self.login(self.coord1)
        self.assertNotContains(self.client.get(self.url(mine)), "Processar fila agora")

    def test_action_buttons_follow_status_and_permissions(self):
        broadcast = self.broadcast(creator=self.coord1)
        self.login(self.coord1)  # só visualização
        page = self.client.get(self.url(broadcast))
        for label in ("Pausar", "Cancelar disparo", "Excluir"):
            self.assertNotContains(page, label)
        self.grant(self.coord1, "disparos", edit=True)
        page = self.client.get(self.url(broadcast))
        self.assertContains(page, "Pausar")
        self.assertContains(page, "Cancelar disparo")
        self.assertNotContains(page, "Retomar")
        self.assertNotContains(page, "Excluir")  # RUNNING não pode ser excluído

    def test_non_admin_does_not_see_voters_outside_their_network(self):
        broadcast = self.broadcast(creator=self.coord1, status=BroadcastStatus.COMPLETED)
        inside = make_voter(self.a, self.cabo1, name="Pessoa Dentro")
        outside = make_voter(self.a, self.cabo2, name="Pessoa Fora")
        make_message(broadcast, inside, status="SENT")
        make_message(broadcast, outside, status="SENT")
        self.login(self.coord1)
        response = self.client.get(self.url(broadcast))
        self.assertContains(response, "Pessoa Dentro")
        self.assertNotContains(response, "Pessoa Fora")
        self.assertNotContains(response, outside.phone)
        self.assertContains(response, "Fora da sua rede")

    def test_deleted_voter_phone_is_masked(self):
        broadcast = self.broadcast(status=BroadcastStatus.COMPLETED)
        voter = make_voter(self.a, self.cabo1)
        make_message(broadcast, voter, status="SENT")
        phone = voter.phone
        voter.delete()
        self.login(self.admin)
        response = self.client.get(self.url(broadcast))
        self.assertContains(response, "Apoiador excluído")
        self.assertNotContains(response, phone)

    def test_deleted_template_is_handled(self):
        broadcast = self.broadcast(status=BroadcastStatus.COMPLETED)
        self.template.delete()
        self.login(self.admin)
        self.assertContains(self.client.get(self.url(broadcast)), "foi excluído")


# ----------------------------------------------------------------------------------------------------- ações


class BroadcastActionTests(Fixtures):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def act(self, broadcast, control, **kw):
        return self.client.post(self.url(broadcast, f"acao/{control}/"), follow=True, **kw)

    def test_pause_and_resume(self):
        broadcast = self.broadcast()
        make_message(broadcast, make_voter(self.a, self.cabo1))
        response = self.act(broadcast, "pause")
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.PAUSED)
        self.assertEqual(response.redirect_chain[0][0], self.url(broadcast))
        self.assertTrue(AuditLog.objects.filter(action="broadcast.pause", entity_id=str(broadcast.pk), user=self.admin).exists())
        self.act(broadcast, "resume")
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)
        self.assertTrue(AuditLog.objects.filter(action="broadcast.resume", entity_id=str(broadcast.pk)).exists())

    def test_resume_requires_a_working_connection(self):
        broadcast = self.broadcast(status=BroadcastStatus.PAUSED)
        self.conn.status = ConnectionStatus.ERROR
        self.conn.save(update_fields=["status"])
        response = self.act(broadcast, "resume")
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.PAUSED)
        self.assertIn("conectada", self.messages_in(response))

    def test_resume_blocked_for_official_connection_without_approved_template(self):
        official = make_connection(self.a, provider="META_CLOUD", default=False)
        broadcast = make_broadcast(self.a, self.admin, self.template, official, status=BroadcastStatus.PAUSED)
        response = self.act(broadcast, "resume")
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.PAUSED)
        self.assertIn("template aprovado", self.messages_in(response))

    def test_cancel_skips_pending_messages(self):
        broadcast = self.broadcast(status=BroadcastStatus.PAUSED)
        pending = make_message(broadcast, make_voter(self.a, self.cabo1), status="PENDING")
        sent = make_message(broadcast, make_voter(self.a, self.cabo1), status="SENT")
        self.act(broadcast, "cancel")
        broadcast.refresh_from_db()
        pending.refresh_from_db()
        sent.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.CANCELLED)
        self.assertIsNotNone(broadcast.finished_at)
        self.assertEqual((pending.status, pending.error), (MessageStatus.SKIPPED, "Cancelado"))
        self.assertEqual(sent.status, MessageStatus.SENT)
        self.assertTrue(AuditLog.objects.filter(action="broadcast.cancel", entity_id=str(broadcast.pk)).exists())

    def test_cancel_scheduled_broadcast(self):
        broadcast = self.broadcast(status=BroadcastStatus.SCHEDULED, scheduled_at=timezone.now() + timedelta(hours=2))
        self.act(broadcast, "cancel")
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.CANCELLED)

    def test_retry_requeues_only_failures_below_attempt_limit(self):
        broadcast = self.broadcast(status=BroadcastStatus.COMPLETED, finished_at=timezone.now())
        retryable = make_message(broadcast, make_voter(self.a, self.cabo1), status="FAILED", attempts=3, error="timeout")
        exhausted = make_message(broadcast, make_voter(self.a, self.cabo1), status="FAILED", attempts=logic.MAX_MANUAL_ATTEMPTS)
        response = self.act(broadcast, "retry")
        broadcast.refresh_from_db()
        retryable.refresh_from_db()
        exhausted.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)
        self.assertIsNone(broadcast.finished_at)
        self.assertEqual((retryable.status, retryable.error), (MessageStatus.PENDING, ""))
        self.assertEqual(exhausted.status, MessageStatus.FAILED)
        self.assertEqual(broadcast.failed_count, 1)  # contadores recalculados
        self.assertIn("1 mensagem", self.messages_in(response))
        self.assertTrue(AuditLog.objects.filter(action="broadcast.retry", entity_id=str(broadcast.pk)).exists())

    def test_retry_without_eligible_failures_changes_nothing(self):
        broadcast = self.broadcast(status=BroadcastStatus.COMPLETED)
        make_message(broadcast, make_voter(self.a, self.cabo1), status="FAILED", attempts=logic.MAX_MANUAL_ATTEMPTS)
        self.act(broadcast, "retry")
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.COMPLETED)

    def test_invalid_transitions_are_refused(self):
        for status, control in (
            (BroadcastStatus.SCHEDULED, "pause"),
            (BroadcastStatus.RUNNING, "resume"),
            (BroadcastStatus.COMPLETED, "cancel"),
            (BroadcastStatus.CANCELLED, "resume"),
            (BroadcastStatus.PAUSED, "retry"),
        ):
            broadcast = self.broadcast(status=status)
            response = self.act(broadcast, control)
            broadcast.refresh_from_db()
            self.assertEqual(broadcast.status, status, (status, control))
            self.assertIn("não está disponível", self.messages_in(response))
        self.assertFalse(AuditLog.objects.filter(action__startswith="broadcast.").exists())

    def test_unknown_control_is_404_and_get_is_405(self):
        broadcast = self.broadcast()
        self.assertEqual(self.client.post(self.url(broadcast, "acao/apagar-tudo/")).status_code, 404)
        self.assertEqual(self.client.get(self.url(broadcast, "acao/pause/")).status_code, 405)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)

    def test_actions_require_edit_permission(self):
        broadcast = self.broadcast(creator=self.coord1)
        self.login(self.coord1)  # só visualização por padrão
        self.assertEqual(self.client.post(self.url(broadcast, "acao/pause/")).status_code, 403)
        self.assertEqual(self.client.post(self.url(broadcast, "excluir/")).status_code, 403)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)
        self.grant(self.coord1, "disparos", edit=True)
        self.assertEqual(self.client.post(self.url(broadcast, "acao/pause/")).status_code, 302)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.PAUSED)

    def test_non_admin_cannot_act_on_someone_elses_broadcast(self):
        broadcast = self.broadcast(creator=self.coord2)
        self.grant(self.coord1, "disparos", edit=True, delete=True)
        self.login(self.coord1)
        for suffix in ("acao/pause/", "acao/cancel/", "excluir/"):
            self.assertEqual(self.client.post(self.url(broadcast, suffix)).status_code, 404, suffix)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)

    def test_csrf_is_enforced(self):
        broadcast = self.broadcast()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url(broadcast, "acao/pause/")).status_code, 403)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)

    def test_delete(self):
        running = self.broadcast(status=BroadcastStatus.RUNNING)
        response = self.client.post(self.url(running, "excluir/"), follow=True)
        self.assertTrue(Broadcast.objects.filter(pk=running.pk).exists())
        self.assertIn("Pause ou cancele", self.messages_in(response))

        paused = self.broadcast(status=BroadcastStatus.PAUSED)
        make_message(paused, make_voter(self.a, self.cabo1))
        response = self.client.post(self.url(paused, "excluir/"))
        self.assertRedirects(response, BASE, fetch_redirect_response=False)
        self.assertFalse(Broadcast.objects.filter(pk=paused.pk).exists())
        self.assertEqual(BroadcastMessage.objects.filter(broadcast_id=paused.pk).count(), 0)
        self.assertTrue(AuditLog.objects.filter(action="broadcast.delete", entity_id=str(paused.pk)).exists())

    def test_process_queue_now_is_admin_only_and_campaign_scoped(self):
        broadcast = self.broadcast()
        make_message(broadcast, make_voter(self.a, self.cabo1))
        self.login(self.coord1)
        self.assertEqual(self.client.post(self.url(broadcast, "processar/")).status_code, 403)
        self.login(self.admin)
        with mock.patch("apps.messaging.views_broadcasts.run_queue_tick", wraps=None) as tick:
            tick.return_value = {"materialized": 0, "sent": 1, "failed": 0, "skipped": 0, "completed": 1, "geocoded": 0}
            response = self.client.post(self.url(broadcast, "processar/"), follow=True)
        tick.assert_called_once_with(campaign_id=self.a.pk, max_messages=50)
        self.assertIn("1 enviada", self.messages_in(response))

    def test_process_queue_now_really_sends(self):
        broadcast = self.broadcast()
        message = make_message(broadcast, make_voter(self.a, self.cabo1))
        with mock.patch(PROVIDER, return_value=FakeProvider()):
            self.client.post(self.url(broadcast, "processar/"))
        message.refresh_from_db()
        broadcast.refresh_from_db()
        self.assertEqual(message.status, MessageStatus.SENT)
        self.assertEqual(broadcast.status, BroadcastStatus.COMPLETED)


# ----------------------------------------------------------------------------------------------------- API do público


class AudienceApiTests(Fixtures):
    def setUp(self):
        super().setUp()
        # coord1: 2 aptos, 1 sem consentimento, 1 descadastrado; coord2: 1 apto; outra campanha: 1 apto
        self.v1 = make_voter(self.a, self.cabo1, neighborhood="Centro")
        self.v2 = make_voter(self.a, self.coord1, neighborhood="Cambuí")
        make_voter(self.a, self.cabo1, consent=False, neighborhood="Centro")
        make_voter(self.a, self.cabo1, opt_out_at=timezone.now(), neighborhood="Centro")
        self.v5 = make_voter(self.a, self.cabo2, neighborhood="Centro")
        make_voter(self.b, self.admin_b)

    def get(self, params=None):
        response = self.client.get(AUDIENCE, params or {})
        return response, (response.json() if response["Content-Type"].startswith("application/json") else None)

    def test_breakdown_for_admin(self):
        self.login(self.admin)
        response, data = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"eligible": 3, "total_matching": 5, "without_opt_in": 1, "opted_out": 1})

    def test_audience_never_exceeds_the_users_network(self):
        self.grant(self.coord1, "disparos", create=True)
        self.login(self.coord1)
        _, data = self.get()
        self.assertEqual(data, {"eligible": 2, "total_matching": 4, "without_opt_in": 1, "opted_out": 1})
        # filtrar por um cabo de outra rede não amplia o escopo (e é recusado)
        response, data = self.get({"cabo": str(self.cabo2.pk)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("rede", data["error"])

    def test_filters_apply(self):
        self.login(self.admin)
        _, data = self.get({"bairro": "Centro"})
        self.assertEqual(data["eligible"], 2)
        _, data = self.get({"bairro": ["Centro", "Cambuí"], "whatsapp": "0"})  # `messageable` é ignorado
        self.assertEqual((data["eligible"], data["total_matching"]), (3, 5))

    def test_requires_login_and_permission_with_json_errors(self):
        response, data = self.get()
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", data)
        self.login(self.coord1)  # apenas visualização
        response, data = self.get()
        self.assertEqual(response.status_code, 403)
        self.login(self.cabo1)
        self.assertEqual(self.get()[0].status_code, 403)

    def test_only_get(self):
        self.login(self.admin)
        self.assertEqual(self.client.post(AUDIENCE, {}).status_code, 405)

    def test_detail_returns_summary_duration_and_samples(self):
        self.login(self.admin)
        response, data = self.get({"bairro": "Centro", "detalhe": "1", "modelo": str(self.template.pk), "velocidade": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["filters_summary"], [{"label": "Bairros", "value": "Centro"}])
        self.assertEqual(data["eligible"], 2)
        self.assertEqual(data["duration_minutes"], 2)
        self.assertEqual(data["duration_label"], "cerca de 2 min")
        self.assertEqual(len(data["samples"]), 2)
        for sample in data["samples"]:
            self.assertTrue(sample["body"].startswith("Olá, Apoiador!") or sample["body"].startswith("Olá, "))
            self.assertNotIn(" Sobrenome", sample["name"])  # só o primeiro nome
            self.assertIn("Aqui é Alfa", sample["body"])

    def test_samples_respect_scope_and_campaign_of_template(self):
        self.grant(self.coord1, "disparos", create=True)
        self.login(self.coord1)
        _, data = self.get({"detalhe": "1", "modelo": str(self.template.pk)})
        self.assertEqual(len(data["samples"]), 2)
        foreign_template = make_template(self.b, self.admin_b)
        _, data = self.get({"detalhe": "1", "modelo": str(foreign_template.pk)})
        self.assertEqual(data["samples"], [])
        _, data = self.get({"detalhe": "1", "modelo": "nao-e-uuid", "velocidade": "abc"})
        self.assertEqual((data["samples"], data["duration_minutes"]), ([], 0))

    def test_samples_limited_to_three(self):
        for _ in range(5):
            make_voter(self.a, self.cabo1)
        self.login(self.admin)
        _, data = self.get({"detalhe": "1", "modelo": str(self.template.pk)})
        self.assertEqual(len(data["samples"]), 3)


# ----------------------------------------------------------------------------------------------------- assistente


class WizardPageTests(Fixtures):
    def test_get_renders_with_templates_connections_and_filters(self):
        self.login(self.admin)
        response = self.client.get(NEW)
        self.assertEqual(response.status_code, 200)
        config = response.context["wizard_config"]
        self.assertEqual([t["name"] for t in config["templates"]], ["Convite"])
        self.assertEqual([c["id"] for c in config["connections"]], [str(self.conn.pk)])
        self.assertEqual(config["state"]["connection"], str(self.conn.pk))
        self.assertEqual(config["state"]["rate"], 20)
        self.assertNotIn("credentials", json.dumps(config))
        self.assertContains(response, "Confirmo que todos os destinatários consentiram")
        self.assertContains(response, "Res. 23.610/2019")
        self.assertNotContains(response, "Somente aptos a receber WhatsApp")  # `messageable` oculto

    def test_wizard_lists_only_own_campaign_data(self):
        make_template(self.b, self.admin_b, name="Modelo alheio")
        make_connection(self.b, name="Conexão alheia")
        make_connection(self.a, name="Conexão desligada", status=ConnectionStatus.DRAFT, default=False)
        self.login(self.admin)
        response = self.client.get(NEW)
        self.assertNotContains(response, "Modelo alheio")
        self.assertNotContains(response, "Conexão alheia")
        self.assertNotContains(response, "Conexão desligada")

    def test_preselected_template_must_belong_to_the_campaign(self):
        foreign = make_template(self.b, self.admin_b)
        self.login(self.admin)
        self.assertEqual(self.client.get(NEW, {"modelo": str(self.template.pk)}).context["wizard_config"]["state"]["template"], str(self.template.pk))
        self.assertEqual(self.client.get(NEW, {"modelo": str(foreign.pk)}).context["wizard_config"]["state"]["template"], "")

    def test_without_templates_shows_call_to_action(self):
        self.template.delete()
        self.login(self.admin)
        self.assertContains(self.client.get(NEW), "Crie um modelo de mensagem primeiro")

    def test_without_connection_shows_call_to_action(self):
        self.conn.delete()
        self.login(self.admin)
        response = self.client.get(NEW)
        self.assertContains(response, "Nenhuma conexão ativa")
        self.assertContains(response, "/painel/whatsapp/")

    def test_official_connection_exposes_template_requirement(self):
        make_connection(self.a, provider="META_CLOUD", name="API oficial", default=False)
        self.login(self.admin)
        rows = {c["name"]: c for c in self.client.get(NEW).context["wizard_config"]["connections"]}
        self.assertTrue(rows["API oficial"]["requiresTemplate"])
        self.assertFalse(rows[self.conn.name]["requiresTemplate"])


class WizardPostTests(Fixtures):
    def setUp(self):
        super().setUp()
        self.voters = [make_voter(self.a, self.cabo1, neighborhood="Centro") for _ in range(3)]
        make_voter(self.a, self.cabo1, consent=False)
        self.login(self.admin)

    def data(self, **extra):
        data = {
            "name": "Convite sábado",
            "template": str(self.template.pk),
            "connection": str(self.conn.pk),
            "rate_per_minute": "20",
            "mode": "now",
            "scheduled_at": "",
            "filters": "{}",
            "consent": "on",
        }
        data.update(extra)
        return data

    def post(self, **extra):
        return self.client.post(NEW, self.data(**extra))

    def assertRejected(self, response, field=None):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Broadcast.objects.count(), 0)
        if field:
            self.assertIn(field, response.context["wizard_config"]["errors"])

    def test_send_now_materializes_and_runs(self):
        response = self.post(filters=json.dumps({"neighborhoods": ["Centro"], "messageable": False}))
        broadcast = Broadcast.objects.get()
        self.assertRedirects(response, f"{BASE}{broadcast.pk}/", fetch_redirect_response=False)
        self.assertEqual(broadcast.status, BroadcastStatus.RUNNING)
        self.assertEqual(broadcast.total_recipients, 3)
        self.assertEqual(broadcast.name, "Convite sábado")
        self.assertEqual(broadcast.campaign_id, self.a.pk)
        self.assertEqual(broadcast.created_by_id, self.admin.pk)
        self.assertEqual((broadcast.template_id, broadcast.connection_id), (self.template.pk, self.conn.pk))
        self.assertEqual(broadcast.rate_per_minute, 20)
        self.assertIsNotNone(broadcast.started_at)
        self.assertEqual(broadcast.filters, {"neighborhoods": ["Centro"]})  # `messageable` nunca é salvo
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=broadcast).count(), 3)
        create = AuditLog.objects.get(action="broadcast.create")
        self.assertEqual(create.entity_id, str(broadcast.pk))
        self.assertEqual(create.details["estimated_recipients"], 3)
        self.assertEqual(create.details["filter_keys"], ["neighborhoods"])
        self.assertNotIn("Centro", str(create.details))  # nada de filtros em texto (podem conter dados pessoais)
        start = AuditLog.objects.get(action="broadcast.start")
        self.assertEqual(start.details, {"recipients": 3})

    def test_schedule_is_stored_in_utc_from_sao_paulo_time(self):
        when = (timezone.now() + timedelta(days=2)).astimezone(logic.CAMPAIGN_TZ).replace(second=0, microsecond=0)
        response = self.post(mode="schedule", scheduled_at=when.strftime("%Y-%m-%dT%H:%M"))
        broadcast = Broadcast.objects.get()
        self.assertRedirects(response, f"{BASE}{broadcast.pk}/", fetch_redirect_response=False)
        self.assertEqual(broadcast.status, BroadcastStatus.SCHEDULED)
        self.assertEqual(broadcast.scheduled_at, when)
        self.assertEqual(broadcast.total_recipients, 0)  # materializa só no horário
        self.assertEqual(BroadcastMessage.objects.count(), 0)
        self.assertTrue(AuditLog.objects.filter(action="broadcast.create").exists())
        self.assertFalse(AuditLog.objects.filter(action="broadcast.start").exists())

    def test_schedule_validation(self):
        past = (timezone.now() - timedelta(hours=1)).astimezone(logic.CAMPAIGN_TZ).strftime("%Y-%m-%dT%H:%M")
        self.assertRejected(self.post(mode="schedule", scheduled_at=past), "scheduled_at")
        self.assertRejected(self.post(mode="schedule", scheduled_at=""), "scheduled_at")
        self.assertRejected(self.post(mode="schedule", scheduled_at="2026-02-31T10:00"), "scheduled_at")
        self.assertRejected(self.post(mode="schedule", scheduled_at="amanhã cedo"), "scheduled_at")
        self.assertRejected(self.post(mode="depois"), "mode")

    def test_template_of_another_campaign_is_rejected(self):
        foreign = make_template(self.b, self.admin_b)
        self.assertRejected(self.post(template=str(foreign.pk)), "template")
        self.assertRejected(self.post(template="nao-e-uuid"), "template")
        self.assertRejected(self.post(template=""), "template")

    def test_connection_of_another_campaign_is_rejected(self):
        foreign = make_connection(self.b)
        self.assertRejected(self.post(connection=str(foreign.pk)), "connection")
        self.assertRejected(self.post(connection="nao-e-uuid"), "connection")

    def test_connection_must_be_connected(self):
        offline = make_connection(self.a, status=ConnectionStatus.ERROR, default=False)
        self.assertRejected(self.post(connection=str(offline.pk)), "connection")

    def test_rate_must_respect_connection_limit(self):
        self.conn.rate_per_minute = 30
        self.conn.save(update_fields=["rate_per_minute"])
        self.assertRejected(self.post(rate_per_minute="31"), "rate_per_minute")
        self.assertRejected(self.post(rate_per_minute="0"), "rate_per_minute")
        self.assertRejected(self.post(rate_per_minute="abc"), "rate_per_minute")
        self.assertRejected(self.post(rate_per_minute=""), "rate_per_minute")
        self.assertEqual(self.post(rate_per_minute="30").status_code, 302)

    def test_consent_is_required(self):
        data = self.data()
        data.pop("consent")
        self.assertRejected(self.client.post(NEW, data), "consent")
        self.assertRejected(self.post(consent=""), "consent")

    def test_name_is_required(self):
        self.assertRejected(self.post(name="ab"), "name")
        self.assertRejected(self.post(name=""), "name")

    def test_official_connection_requires_approved_template_name(self):
        official = make_connection(self.a, provider="META_CLOUD", default=False)
        self.assertRejected(self.post(connection=str(official.pk)), "template")
        approved = make_template(self.a, self.admin, provider_template_name="convite_evento")
        response = self.post(connection=str(official.pk), template=str(approved.pk))
        self.assertEqual(response.status_code, 302)

    def test_invalid_filters_are_rejected_instead_of_widening_the_audience(self):
        for raw in ("não é json", "[]", '"texto"', json.dumps({"age_min": 999}), json.dumps({"genders": ["X"]}), json.dumps({"created_from": "ontem"})):
            self.assertRejected(self.post(filters=raw), "filters")

    def test_team_filters_must_be_inside_the_users_network(self):
        self.grant(self.coord1, "disparos", create=True)
        self.login(self.coord1)
        outside = json.dumps({"registered_by_ids": [str(self.cabo2.pk)]})
        self.assertRejected(self.post(filters=outside), "filters")
        foreign = json.dumps({"registered_by_ids": [str(self.admin_b.pk)]})
        self.assertRejected(self.post(filters=foreign), "filters")
        inside = json.dumps({"registered_by_ids": [str(self.cabo1.pk)]})
        self.assertEqual(self.post(filters=inside).status_code, 302)

    def test_audience_without_eligible_voters_is_rejected(self):
        self.assertRejected(self.post(filters=json.dumps({"neighborhoods": ["Bairro Sem Ninguém"]})))
        Broadcast.objects.all().delete()
        # tem apoiadores, mas nenhum com consentimento
        make_voter(self.a, self.cabo2, consent=False, neighborhood="Sem Consentimento")
        self.assertRejected(self.post(filters=json.dumps({"neighborhoods": ["Sem Consentimento"]})))

    def test_failed_post_restores_the_wizard_state_at_the_right_step(self):
        response = self.post(name="ab", filters=json.dumps({"neighborhoods": ["Centro"]}))
        config = response.context["wizard_config"]
        self.assertEqual(config["state"]["name"], "ab")
        self.assertEqual(config["state"]["filters"], {"neighborhoods": ["Centro"]})
        self.assertEqual(config["step"], 0)
        self.assertTrue(config["state"]["consent"])
        response = self.post(rate_per_minute="9999")
        self.assertEqual(response.context["wizard_config"]["step"], 2)
        self.assertEqual(response.context["filters"], {})

    def test_permissions(self):
        self.login(self.coord1)  # só visualização
        self.assertEqual(self.post().status_code, 403)
        self.login(self.cabo1)
        self.assertEqual(self.post().status_code, 403)
        self.client.logout()
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(Broadcast.objects.count(), 0)

    def test_coordinator_broadcast_only_reaches_their_network(self):
        make_voter(self.a, self.cabo2)  # fora da rede do coord1
        self.grant(self.coord1, "disparos", create=True)
        self.login(self.coord1)
        self.post()
        broadcast = Broadcast.objects.get()
        self.assertEqual(broadcast.created_by_id, self.coord1.pk)
        self.assertEqual(broadcast.total_recipients, 3)
        owners = set(
            BroadcastMessage.objects.filter(broadcast=broadcast).values_list("voter__registered_by_id", flat=True)
        )
        self.assertEqual(owners, {self.cabo1.pk})

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(NEW, self.data()).status_code, 403)
        self.assertEqual(Broadcast.objects.count(), 0)

    def test_creation_is_rate_limited(self):
        for _ in range(20):
            self.post(name="ab")  # inválidos também contam
        response = self.post()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], BASE)
        self.assertEqual(Broadcast.objects.count(), 0)

    def test_form_resubmission_does_not_create_duplicates(self):
        first = self.post()
        second = self.post()
        broadcast = Broadcast.objects.get()
        self.assertEqual(first["Location"], second["Location"])
        self.assertEqual(first["Location"], f"{BASE}{broadcast.pk}/")
        self.assertEqual(BroadcastMessage.objects.filter(broadcast=broadcast).count(), 3)
        self.assertEqual(AuditLog.objects.filter(action="broadcast.create").count(), 1)
        # outro nome = outro disparo
        self.post(name="Outro convite")
        self.assertEqual(Broadcast.objects.count(), 2)

    def test_immediate_start_failure_leaves_broadcast_scheduled_for_the_worker(self):
        with mock.patch("apps.messaging.views_broadcasts.materialize_broadcast", side_effect=RuntimeError("boom")):
            response = self.client.post(NEW, self.data(), follow=True)
        broadcast = Broadcast.objects.get()
        self.assertEqual(broadcast.status, BroadcastStatus.SCHEDULED)
        self.assertLessEqual(broadcast.scheduled_at, timezone.now())  # o worker assume no próximo ciclo
        self.assertIn("será iniciado", self.messages_in(response))


# ----------------------------------------------------------------------------------------------------- cron


@override_settings(CRON_SECRET="segredo-do-cron-1234")
class CronTickTests(Fixtures):
    URL = "/api/cron/tick/"

    def test_requires_secret(self):
        self.assertEqual(self.client.get(self.URL).status_code, 401)
        self.assertEqual(self.client.get(self.URL, HTTP_AUTHORIZATION="Bearer errado").status_code, 401)
        self.assertEqual(self.client.get(self.URL, {"secret": "errado"}).status_code, 401)
        self.assertEqual(self.client.get(self.URL, HTTP_AUTHORIZATION="Basic segredo-do-cron-1234").status_code, 401)
        self.assertEqual(self.client.get(self.URL, {"secret": ""}).status_code, 401)

    @override_settings(CRON_SECRET="")
    def test_not_configured_returns_503(self):
        self.assertEqual(self.client.get(self.URL, {"secret": ""}).status_code, 503)
        self.assertEqual(self.client.get(self.URL, HTTP_AUTHORIZATION="Bearer ").status_code, 503)

    def test_bearer_and_query_secret_run_a_tick(self):
        broadcast = self.broadcast(status=BroadcastStatus.SCHEDULED)
        make_voter(self.a, self.cabo1)
        with mock.patch(PROVIDER, return_value=FakeProvider()):
            response = self.client.get(self.URL, HTTP_AUTHORIZATION="Bearer segredo-do-cron-1234")
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual((report["materialized"], report["sent"], report["completed"]), (1, 1, 1))
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.COMPLETED)
        with mock.patch(PROVIDER, return_value=FakeProvider()):
            again = self.client.post(self.URL + "?secret=segredo-do-cron-1234")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["sent"], 0)

    def test_csrf_exempt_and_other_methods_refused(self):
        client = Client(enforce_csrf_checks=True)
        with mock.patch(PROVIDER, return_value=FakeProvider()):
            ok = client.post(self.URL, HTTP_AUTHORIZATION="Bearer segredo-do-cron-1234")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(client.put(self.URL, HTTP_AUTHORIZATION="Bearer segredo-do-cron-1234").status_code, 405)

    def test_wrong_secret_does_not_run_the_queue(self):
        broadcast = self.broadcast(status=BroadcastStatus.SCHEDULED)
        make_voter(self.a, self.cabo1)
        self.client.get(self.URL, {"secret": "outro"})
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, BroadcastStatus.SCHEDULED)
