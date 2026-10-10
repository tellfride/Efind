"""Ação do ADMIN "Localizar pendentes agora": reprocessa a fila de geocodificação SOMENTE da campanha do usuário.

Por que não chamar `apps.geo.geocode.process_pending_geocoding` direto: ele consome a fila de TODAS as campanhas
(`Voter.objects.filter(geo_status=PENDING)` sem filtro de campanha), então o clique de um administrador gastaria o
tempo da ação (e as chamadas ao Nominatim, limitadas a 1/s) com eleitores de outros candidatos. Aqui o mesmo
trabalho é feito eleitor a eleitor com `geocode_voter`, restrito ao escopo do usuário.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from apps.core.access import voter_scope
from apps.core.constants import GeoStatus
from apps.geo.geocode import geocode_voter

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 15
# O Nominatim aceita 1 requisição/s: não iniciamos novos eleitores depois deste tempo (a ação responde dentro do
# timeout do servidor web; o worker continua o restante em segundo plano)
TIME_BUDGET_SECONDS = 25.0


@dataclass(frozen=True)
class GeocodeRunResult:
    processed: int  # eleitores processados nesta rodada
    located: int  # dos processados, quantos ganharam coordenadas
    failed: int  # dos processados, quantos continuam sem localização
    remaining: int  # eleitores ainda na fila da campanha


def run_campaign_geocoding(
    user, limit: int = DEFAULT_LIMIT, *, time_budget: float = TIME_BUDGET_SECONDS
) -> GeocodeRunResult:
    """Devolve à fila os eleitores FAILED da campanha e processa até `limit` (os nunca processados primeiro)."""
    scope = voter_scope(user)

    # Primeiro os que nunca foram processados; depois os que falharam (os mais antigos antes)
    ids = list(scope.filter(geo_status=GeoStatus.PENDING).order_by("created_at").values_list("id", flat=True)[:limit])
    if len(ids) < limit:
        ids += list(
            scope.filter(geo_status=GeoStatus.FAILED)
            .order_by("updated_at")
            .values_list("id", flat=True)[: limit - len(ids)]
        )

    # Falhas voltam para a fila (o worker continua o restante em segundo plano)
    scope.filter(geo_status=GeoStatus.FAILED).update(geo_status=GeoStatus.PENDING)

    started = time.monotonic()
    processed: list = []
    for voter_id in ids:
        if time.monotonic() - started > time_budget:
            break
        try:
            geocode_voter(voter_id)
        except Exception:  # noqa: BLE001 - uma falha não pode interromper os demais
            logger.exception("Falha ao geocodificar eleitor do mapa")
            scope.filter(pk=voter_id).update(geo_status=GeoStatus.FAILED)
        processed.append(voter_id)

    statuses = list(scope.filter(pk__in=processed).values_list("geo_status", flat=True)) if processed else []
    located = sum(1 for s in statuses if s in (GeoStatus.OK, GeoStatus.APPROXIMATE))
    failed = sum(1 for s in statuses if s == GeoStatus.FAILED)
    remaining = scope.filter(geo_status=GeoStatus.PENDING).count()
    return GeocodeRunResult(processed=len(processed), located=located, failed=failed, remaining=remaining)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _plural(n: int, one: str, many: str) -> str:
    return f"{_fmt(n)} {one if n == 1 else many}"


def geocode_run_message(result: GeocodeRunResult) -> tuple[str, str]:
    """(nível, mensagem) exibidos no toast após "Localizar pendentes agora". Nível: success | warning | info."""
    if result.processed == 0:
        return "info", "Não há eleitores pendentes de localização."
    parts = [_plural(result.located, "eleitor localizado", "eleitores localizados")]
    if result.failed:
        parts.append(_plural(result.failed, "endereço não encontrado", "endereços não encontrados"))
    message = ", ".join(parts) + "."
    if result.remaining == 1:
        message += " 1 eleitor continua na fila e será processado em segundo plano."
    elif result.remaining > 1:
        message += f" {_fmt(result.remaining)} eleitores continuam na fila e serão processados em segundo plano."
    level = "warning" if result.failed and not result.located else "success"
    return level, message
