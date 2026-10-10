"""Simulador — não envia nenhuma mensagem real. Gera ids "sbx_…", simula falhas conforme a taxa configurada e,
depois de alguns segundos, eventos de entrega/leitura como se viessem do webhook (threading.Timer chamando
apps.whatsapp.webhook.apply_webhook_events)."""

from __future__ import annotations

import logging
import random
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from django.utils import timezone

from ..types import OutgoingMessage, ProviderDefinition, ProviderField, SendResult, TestResult, WebhookEvent, WebhookRequest
from . import common
from .cloud_api import parse_cloud_api_webhook_body

logger = logging.getLogger(__name__)

SANDBOX_DEFAULT_FAILURE_RATE = 0.05
SANDBOX_MAX_FAILURE_RATE = 0.5
MAX_EMIT_RETRIES = 2
EMIT_RETRY_DELAY_SECONDS = 2.0


def parse_failure_rate(value: str | None) -> float:
    """"0,1" | "0.1" | "" → número entre 0 e 0,5 (padrão 0,05)."""
    raw = (value or "").strip().replace(",", ".")
    if not raw:
        return SANDBOX_DEFAULT_FAILURE_RATE
    try:
        n = float(raw)
    except ValueError:
        return SANDBOX_DEFAULT_FAILURE_RATE
    if n != n:  # NaN
        return SANDBOX_DEFAULT_FAILURE_RATE
    return min(SANDBOX_MAX_FAILURE_RATE, max(0.0, n))


@dataclass
class SimulationPlan:
    delivered_after: float  # segundos
    read_after: float | None  # None = a mensagem não será lida


def plan_simulated_statuses(rng: Callable[[], float] = random.random) -> SimulationPlan:
    """Entregue em 1–4 s; ~60% lidas em 3–10 s (sempre depois da entrega)."""
    delivered_after = round(1.0 + rng() * 3.0, 3)
    will_read = rng() < 0.6
    read_after = max(delivered_after + 0.5, round(3.0 + rng() * 7.0, 3)) if will_read else None
    return SimulationPlan(delivered_after=delivered_after, read_after=read_after)


# ------------------------------------------------------------------------------------------------ Agendamento


def _run_in_thread(fn: Callable[[], None]) -> None:
    """Executa `fn` numa thread própria, fechando a conexão de banco dela ao terminar."""
    from django.db import connection

    try:
        fn()
    finally:
        connection.close()


def start_timer(delay: float, fn: Callable[[], None]) -> threading.Timer:
    """Agenda `fn` após `delay` segundos. Thread daemon: nunca impede o encerramento do processo."""
    timer = threading.Timer(delay, _run_in_thread, args=(fn,))
    timer.daemon = True
    timer.start()
    return timer


def emit_events(target: SimpleNamespace, events: list[WebhookEvent], attempt: int = 0) -> None:
    """Aplica os eventos simulados à conexão. A mensagem pode ainda não ter o provider_message_id gravado no
    banco (o worker grava depois do envio): tenta de novo até duas vezes."""
    from ..webhook import apply_webhook_events

    try:
        result = apply_webhook_events(target, events)
        if result.matched == 0 and attempt < MAX_EMIT_RETRIES:
            start_timer(EMIT_RETRY_DELAY_SECONDS, lambda: emit_events(target, events, attempt + 1))
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao simular status no simulador: %s", type(exc).__name__)


def schedule_simulation(target: SimpleNamespace, provider_message_id: str, plan: SimulationPlan) -> None:
    def fire(status: str, delay: float) -> None:
        def job() -> None:
            event = WebhookEvent(
                kind="status", provider_message_id=provider_message_id, status=status, timestamp=timezone.now()
            )
            emit_events(target, [event])

        start_timer(delay, job)

    fire("DELIVERED", plan.delivered_after)
    if plan.read_after is not None:
        fire("READ", plan.read_after)


class SandboxProvider:
    key = "SANDBOX"

    def __init__(self, credentials: dict, rng: Callable[[], float] = random.random):
        self.creds = common.normalize_credentials(credentials)  # aceita failureRate (seed) e failure_rate
        self.rng = rng
        self.failure_rate = parse_failure_rate(self.creds.get("failure_rate"))
        connection_id, campaign_id = self.creds.get("__connection_id"), self.creds.get("__campaign_id")
        self.target = SimpleNamespace(id=connection_id, campaign_id=campaign_id) if connection_id and campaign_id else None

    def send(self, message: OutgoingMessage) -> SendResult:
        if not common.is_valid_recipient(message.to):
            return SendResult(ok=False, error="Número de destino inválido", retryable=False)
        if not (message.text or "").strip() and message.template is None and message.media is None:
            return SendResult(ok=False, error="Mensagem vazia", retryable=False)
        if self.rng() < self.failure_rate:
            return SendResult(
                ok=False, error="Falha simulada pelo simulador (nenhuma mensagem real foi enviada)", retryable=False
            )
        provider_message_id = "sbx_" + secrets.token_hex(12)
        if self.target is not None:
            schedule_simulation(self.target, provider_message_id, plan_simulated_statuses(self.rng))
        return SendResult(ok=True, provider_message_id=provider_message_id)

    def test_connection(self) -> TestResult:
        return TestResult(ok=True, message="Simulador pronto — nenhuma mensagem real é enviada.")


def _parse_webhook(req: WebhookRequest) -> list[WebhookEvent]:
    # Aceita payloads no formato da Cloud API (útil para testar o webhook localmente)
    return parse_cloud_api_webhook_body(req.raw_body)


SANDBOX = ProviderDefinition(
    key="SANDBOX",
    label="Simulador (testes)",
    description=(
        "Simula envios, entregas e leituras sem enviar nenhuma mensagem real. Ideal para treinar a equipe e testar "
        "disparos antes de usar a API oficial."
    ),
    official=False,
    setup_steps=[
        "Nenhuma credencial é necessária: o simulador funciona imediatamente.",
        "Os disparos feitos por esta conexão aparecem como enviados, entregues e lidos alguns segundos depois — sem nenhuma mensagem real.",
        "Use a taxa de falhas para ver como o sistema trata erros de envio.",
        "Antes da campanha, cadastre uma conexão oficial (Meta, 360dialog ou Twilio) e defina-a como padrão.",
    ],
    fields=[
        ProviderField(
            name="failure_rate",
            label="Taxa de falhas simuladas",
            placeholder="0,05",
            help="Proporção de envios que falham de propósito, de 0 a 0,5 (ex.: 0,05 = 5%).",
        ),
    ],
    requires_approved_template=False,
    create=lambda credentials: SandboxProvider(credentials),
    parse_webhook=_parse_webhook,
)
