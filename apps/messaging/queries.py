"""Consultas de modelos/disparos usadas por views, formulários e serviços. Tudo limitado à campanha do usuário
(e, nos disparos, ao escopo de visibilidade: ADMIN vê todos; os demais só os que criaram)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from django.db.models import Count, Q, QuerySet

from apps.core.access import MESSAGEABLE_Q, team_scope, voters_queryset
from apps.core.constants import (
    BroadcastStatus,
    ConnectionStatus,
    Gender,
    Role,
    SupportLevel,
    VoterSource,
    label_of,
)
from apps.core.voter_filters import sanitize_voter_filters
from apps.whatsapp import registry
from apps.whatsapp.models import WhatsAppConnection

from .logic import TEMPLATE_LOCKING_STATUSES, send_blocker
from .models import Broadcast, MessageTemplate

# --------------------------------------------------------------------------------------------- escopo


def template_scope(user) -> QuerySet[MessageTemplate]:
    """Modelos da campanha do usuário (modelos pertencem à campanha, sem escopo hierárquico)."""
    return MessageTemplate.objects.filter(campaign_id=user.campaign_id)


def get_template_in_campaign(user, pk) -> MessageTemplate | None:
    try:
        return template_scope(user).filter(pk=uuid.UUID(str(pk))).first()
    except (ValueError, TypeError, AttributeError):
        return None


def broadcast_scope(user) -> QuerySet[Broadcast]:
    """Disparos visíveis: ADMIN vê todos da campanha; os demais, apenas os que criaram."""
    qs = Broadcast.objects.filter(campaign_id=user.campaign_id)
    return qs if user.role == Role.ADMIN else qs.filter(created_by_id=user.id)


def get_broadcast_in_scope(user, pk) -> Broadcast | None:
    try:
        return (
            broadcast_scope(user)
            .select_related("template", "connection", "created_by")
            .filter(pk=uuid.UUID(str(pk)))
            .first()
        )
    except (ValueError, TypeError, AttributeError):
        return None


def connected_connections(user) -> QuerySet[WhatsAppConnection]:
    """Conexões da campanha prontas para enviar (padrão primeiro)."""
    return WhatsAppConnection.objects.filter(campaign_id=user.campaign_id, status=ConnectionStatus.CONNECTED).order_by(
        "-is_default", "name"
    )


def templates_locked_by_broadcasts(campaign_id) -> set:
    """Ids dos modelos usados por disparos agendados, em andamento ou pausados (não podem ser excluídos)."""
    return set(
        Broadcast.objects.filter(
            campaign_id=campaign_id, status__in=TEMPLATE_LOCKING_STATUSES, template__isnull=False
        )
        .order_by()
        .values_list("template_id", flat=True)
        .distinct()
    )


def template_in_use_by(campaign_id, template_id) -> Broadcast | None:
    return (
        Broadcast.objects.filter(campaign_id=campaign_id, template_id=template_id, status__in=TEMPLATE_LOCKING_STATUSES)
        .order_by("-created_at")
        .first()
    )


# --------------------------------------------------------------------------------------------- contagens


def message_status_counts(broadcast_ids) -> dict[Any, dict[str, int]]:
    """{broadcast_id: {status: n}} numa única consulta (evita N+1 nas listas)."""
    from .models import BroadcastMessage

    out: dict[Any, dict[str, int]] = defaultdict(dict)
    rows = (
        BroadcastMessage.objects.filter(broadcast_id__in=list(broadcast_ids))
        .order_by()
        .values_list("broadcast_id", "status")
        .annotate(n=Count("id"))
    )
    for broadcast_id, status, n in rows:
        out[broadcast_id][status] = n
    return out


def audience_counts(user, filters: Mapping[str, Any]) -> dict[str, int]:
    """Quebra do público (sempre dentro do escopo do usuário): quem receberá e por que alguém ficou de fora."""
    base = {k: v for k, v in filters.items() if k != "messageable"}
    totals = voters_queryset(user, base).aggregate(
        total=Count("id"),
        eligible=Count("id", filter=MESSAGEABLE_Q),
        opted_out=Count("id", filter=Q(opt_out_at__isnull=False)),
    )
    total = totals["total"] or 0
    eligible = totals["eligible"] or 0
    opted_out = totals["opted_out"] or 0
    return {
        "eligible": eligible,
        "total_matching": total,
        # Cadastrados que nunca autorizaram (ou sem registro de consentimento) e não pediram descadastro
        "without_opt_in": max(0, total - eligible - opted_out),
        "opted_out": opted_out,
    }


def team_ids_in_scope(user, filters: Mapping[str, Any]) -> bool:
    """Os ids de equipe usados nos filtros pertencem à campanha e ao escopo do usuário?"""
    ids = {*filters.get("registered_by_ids", []), *filters.get("coordinator_ids", [])}
    if not ids:
        return True
    return team_scope(user).filter(pk__in=ids).count() == len(ids)


# --------------------------------------------------------------------------------------------- envio


def broadcast_send_problem(broadcast: Broadcast) -> str | None:
    """Pode (re)começar a enviar? Confere conexão, provedor e template aprovado.
    Retorna a mensagem para o usuário, ou None quando está tudo certo."""
    connection = broadcast.connection
    definition = registry.get_provider_definition(connection.provider) if connection is not None else None
    blocker = send_blocker(
        connection=connection,
        campaign_id=broadcast.campaign_id,
        provider_known=definition is not None,
        requires_approved_template=bool(definition and definition.requires_approved_template),
        template=broadcast.template,
    )
    if blocker is None:
        return None
    if blocker.code == "template_required":
        return (
            "A conexão usa a API oficial, que exige template aprovado. Informe o nome do template aprovado no "
            "modelo antes de continuar."
        )
    return f"{blocker.message} Verifique em Conexão da API."


# --------------------------------------------------------------------------------------------- resumo do público

_LIST_FILTERS = (
    ("neighborhoods", "Bairros"),
    ("cities", "Cidades"),
    ("support_levels", "Nível de apoio"),
    ("genders", "Gênero"),
    ("sources", "Origem do cadastro"),
    ("tags", "Tags"),
    ("electoral_zones", "Zona eleitoral"),
)
_ENUM_LABELS = {"support_levels": SupportLevel, "genders": Gender, "sources": VoterSource}


def describe_filters(filters: Mapping[str, Any] | None, campaign_id) -> list[tuple[str, str]]:
    """Filtros do público em pares (rótulo, texto) para exibir ao usuário. Nomes de equipe vêm da campanha."""
    from apps.accounts.models import User

    f = sanitize_voter_filters(filters)
    team_ids = [*f.get("registered_by_ids", []), *f.get("coordinator_ids", [])]
    names = (
        {str(pk): name for pk, name in User.objects.filter(campaign_id=campaign_id, pk__in=team_ids).values_list("pk", "name")}
        if team_ids
        else {}
    )
    out: list[tuple[str, str]] = []
    if f.get("q"):
        out.append(("Busca", f["q"]))
    for key, label in _LIST_FILTERS:
        values = f.get(key)
        if values:
            enum = _ENUM_LABELS.get(key)
            out.append((label, ", ".join(label_of(enum, v) if enum else str(v) for v in values)))
    if f.get("coordinator_ids"):
        out.append(("Coordenadores", ", ".join(names.get(v, "Removido") for v in f["coordinator_ids"])))
    if f.get("registered_by_ids"):
        out.append(("Cadastrado por", ", ".join(names.get(v, "Removido") for v in f["registered_by_ids"])))
    age_min, age_max = f.get("age_min"), f.get("age_max")
    if age_min is not None and age_max is not None:
        out.append(("Idade", f"{age_min} a {age_max} anos"))
    elif age_min is not None:
        out.append(("Idade", f"a partir de {age_min} anos"))
    elif age_max is not None:
        out.append(("Idade", f"até {age_max} anos"))
    start, end = f.get("created_from"), f.get("created_to")
    if start or end:
        fmt = lambda iso: "/".join(reversed(iso.split("-")))  # noqa: E731 — "2026-01-31" → "31/01/2026"
        out.append(("Cadastrados", f"de {fmt(start)} a {fmt(end)}" if start and end else f"a partir de {fmt(start)}" if start else f"até {fmt(end)}"))
    if f.get("has_geo") is True:
        out.append(("Localização no mapa", "Com localização"))
    elif f.get("has_geo") is False:
        out.append(("Localização no mapa", "Sem localização"))
    return out


def status_label(status: str) -> str:
    return label_of(BroadcastStatus, status)
