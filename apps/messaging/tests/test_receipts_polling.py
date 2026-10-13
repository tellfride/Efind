"""Regressão (QA no navegador): ao concluir o envio, a página do disparo precisa continuar atualizando por um tempo,
porque as confirmações de entrega/leitura chegam depois por webhook (antes ficavam congeladas em 0)."""

from datetime import timedelta

from django.utils import timezone

from apps.core.constants import BroadcastStatus
from apps.messaging.models import Broadcast

from .helpers import MessagingTestCase, make_broadcast, make_connection, make_template


class ReceiptsPollingTests(MessagingTestCase):
    def make(self, status, finished_ago=None):
        broadcast = make_broadcast(self.a, self.admin, make_template(self.a, self.admin), make_connection(self.a), status=status)
        if finished_ago is not None:
            Broadcast.objects.filter(pk=broadcast.pk).update(finished_at=timezone.now() - finished_ago)
        return broadcast

    def page(self, broadcast):
        self.login(self.admin)
        return self.client.get(f"/painel/mensagens/disparos/{broadcast.pk}/")

    def test_running_polls_every_5_seconds(self):
        page = self.page(self.make(BroadcastStatus.RUNNING))
        self.assertContains(page, 'hx-trigger="every 5s"')
        self.assertContains(page, "a cada 5 segundos")

    def test_recently_completed_keeps_polling_slowly_for_receipts(self):
        page = self.page(self.make(BroadcastStatus.COMPLETED, finished_ago=timedelta(minutes=5)))
        self.assertContains(page, 'hx-trigger="every 15s"')
        self.assertContains(page, "Confirmações de entrega e leitura ainda podem chegar")
        self.assertNotContains(page, "Processar fila agora")  # não é mais um disparo "vivo"

    def test_old_completed_stops_polling(self):
        page = self.page(self.make(BroadcastStatus.COMPLETED, finished_ago=timedelta(hours=2)))
        self.assertNotContains(page, "hx-trigger")
        self.assertNotContains(page, "atualizando a cada")

    def test_cancelled_and_paused_do_not_poll(self):
        for status in (BroadcastStatus.CANCELLED, BroadcastStatus.PAUSED):
            page = self.page(self.make(status, finished_ago=timedelta(minutes=1)))
            self.assertNotContains(page, "hx-trigger", msg_prefix=status)

    def test_partial_refresh_keeps_polling_attributes(self):
        broadcast = self.make(BroadcastStatus.COMPLETED, finished_ago=timedelta(minutes=1))
        self.login(self.admin)
        partial = self.client.get(f"/painel/mensagens/disparos/{broadcast.pk}/", HTTP_HX_REQUEST="true")
        self.assertContains(partial, 'hx-trigger="every 15s"')
        self.assertNotContains(partial, "<html")
