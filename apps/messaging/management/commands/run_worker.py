"""Worker da fila de disparos: `manage.py run_worker` (outro terminal / serviço do servidor).

A cada 3 segundos roda um ciclo (`run_queue_tick`): materializa disparos agendados, envia as mensagens respeitando o
limite por minuto, atualiza contadores e geocodifica eleitores pendentes. SIGINT/SIGTERM terminam o ciclo atual e
encerram. Os logs têm apenas contagens (nunca telefones, nomes ou textos).
"""

from __future__ import annotations

import logging
import signal
import threading

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.messaging.processor import run_queue_tick, tick_had_activity

logger = logging.getLogger("apps.messaging.worker")

DEFAULT_INTERVAL = 3.0


def format_report(report: dict) -> str:
    """Resumo de uma linha do ciclo (somente contagens)."""
    return (
        f"fila: {report.get('materialized', 0)} iniciado(s), {report.get('sent', 0)} enviada(s), "
        f"{report.get('failed', 0)} falha(s), {report.get('skipped', 0)} ignorada(s), "
        f"{report.get('completed', 0)} concluído(s), {report.get('geocoded', 0)} geocodificado(s)"
    )


class Command(BaseCommand):
    help = "Processa a fila de disparos de WhatsApp (e a geocodificação pendente) em ciclos de poucos segundos."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Executa um único ciclo e sai.")
        parser.add_argument(
            "--interval",
            type=float,
            default=DEFAULT_INTERVAL,
            help=f"Segundos entre os ciclos (padrão: {DEFAULT_INTERVAL:g}).",
        )

    def handle(self, *args, **options):
        stop = threading.Event()

        def request_stop(signum, frame):  # noqa: ARG001 — termina depois do ciclo atual
            stop.set()

        previous = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[sig] = signal.signal(sig, request_stop)
            except ValueError:  # fora da thread principal (ex.: testes)
                break

        interval = max(0.5, float(options["interval"]))
        if not options["once"]:
            self.stdout.write("Worker de disparos iniciado. Ctrl+C para encerrar.")
        try:
            while not stop.is_set():
                close_old_connections()
                try:
                    report = run_queue_tick()
                except Exception as exc:  # noqa: BLE001 — o worker nunca morre por um ciclo ruim
                    logger.error("Falha no ciclo da fila (%s)", type(exc).__name__)
                    report = None
                if report is not None and (tick_had_activity(report) or options["once"]):
                    line = format_report(report)
                    logger.info(line)
                    self.stdout.write(line)
                if options["once"]:
                    break
                stop.wait(interval)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            close_old_connections()
        if not options["once"]:
            self.stdout.write("Worker encerrado.")
