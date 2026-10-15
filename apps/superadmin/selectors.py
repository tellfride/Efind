"""Leituras do super admin. PRIVACIDADE: apoiadores só entram aqui como contagens agregadas (count/aggregate);
nenhuma linha de apoiador (nome, telefone, e-mail, endereço) é carregada para o super admin.
Sem N+1: contagens por campanha vêm de subconsultas anotadas na própria listagem."""

from __future__ import annotations

import datetime as dt
import json
import re
from datetime import timedelta
from typing import Any

from django.db.models import Count, IntegerField, Max, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import User
from apps.auditlog.actions import action_label
from apps.auditlog.models import AuditLog
from apps.campaigns.models import Campaign
from apps.core.access import MESSAGEABLE_Q, SAO_PAULO
from apps.core.constants import (
    BroadcastStatus,
    CampaignStatus,
    ConnectionStatus,
    MessageStatus,
    Office,
    Role,
    label_of,
)
from apps.dashboards.models import Dashboard
from apps.messaging.models import Broadcast, BroadcastMessage, MessageTemplate
from apps.voters.models import Voter
from apps.whatsapp.models import WhatsAppConnection

from .forms import DEFAULT_PRIMARY_COLOR, PLATFORM_SCOPE

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


# ---------------------------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------------------------


def campaigns_with_counts() -> QuerySet:
    """Campanhas com `user_count` e `voter_count` (subconsultas: sem N+1 e sem produto cartesiano)."""
    users = User.objects.filter(campaign=OuterRef("pk")).order_by().values("campaign").annotate(n=Count("pk")).values("n")
    voters = Voter.objects.filter(campaign=OuterRef("pk")).order_by().values("campaign").annotate(n=Count("pk")).values("n")
    return Campaign.objects.annotate(
        user_count=Coalesce(Subquery(users, output_field=IntegerField()), 0),
        voter_count=Coalesce(Subquery(voters, output_field=IntegerField()), 0),
    )


def search_campaigns(qs: QuerySet, q: str = "", status: str = "") -> QuerySet:
    """Busca por candidato, nome de urna, número, partido, cidade ou identificador + filtro de status."""
    q = (q or "").strip()
    if q:
        qs = qs.filter(
            Q(candidate_name__icontains=q)
            | Q(ballot_name__icontains=q)
            | Q(ballot_number__icontains=q)
            | Q(party__icontains=q)
            | Q(city__icontains=q)
            | Q(slug__icontains=q)
        )
    if status in CampaignStatus.values:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at", "pk")


def decorate_campaign(campaign: Campaign) -> Campaign:
    """Atributos de exibição (rótulos, local, cor segura) usados pelos templates."""
    campaign.office_label = label_of(Office, campaign.office)
    campaign.place = "/".join(p for p in (campaign.city, campaign.state) if p) or "—"
    color = campaign.primary_color or ""
    campaign.display_color = color if HEX_COLOR.fullmatch(color) else DEFAULT_PRIMARY_COLOR
    campaign.mark = (campaign.ballot_number or campaign.ballot_name[:1] or "?")[:2].upper()
    return campaign


def decorate_campaigns(campaigns) -> list[Campaign]:
    return [decorate_campaign(c) for c in campaigns]


def platform_overview(recent_limit: int = 10) -> dict[str, Any]:
    """Indicadores da plataforma e campanhas mais recentes."""
    totals = Campaign.objects.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(status=CampaignStatus.ACTIVE)),
        suspended=Count("pk", filter=Q(status=CampaignStatus.SUSPENDED)),
    )
    since = timezone.now() - timedelta(days=7)
    voters = Voter.objects.aggregate(total=Count("pk"), last7=Count("pk", filter=Q(created_at__gte=since)))
    return {
        "campaigns_total": totals["total"],
        "campaigns_active": totals["active"],
        "campaigns_suspended": totals["suspended"],
        "campaign_users": User.objects.filter(campaign__isnull=False).count(),
        "voters_total": voters["total"],
        "voters_last7": voters["last7"],
        "recent": decorate_campaigns(campaigns_with_counts().order_by("-created_at", "pk")[:recent_limit]),
    }


def campaign_admins(campaign: Campaign) -> list[User]:
    """Administradores da campanha (contas de equipe, não dados de apoiadores)."""
    return list(
        User.objects.filter(campaign=campaign, role=Role.ADMIN)
        .only("id", "name", "email", "phone", "is_active", "last_login", "created_at")
        .order_by("-is_active", "created_at", "pk")
    )


def super_users() -> list[User]:
    return list(
        User.objects.filter(role=Role.SUPER_ADMIN)
        .only("id", "name", "email", "phone", "is_active", "last_login", "created_at")
        .order_by("-is_active", "created_at", "pk")
    )


BROADCAST_TONES = {
    BroadcastStatus.DRAFT: "gray",
    BroadcastStatus.SCHEDULED: "blue",
    BroadcastStatus.RUNNING: "brand",
    BroadcastStatus.PAUSED: "yellow",
    BroadcastStatus.COMPLETED: "green",
    BroadcastStatus.CANCELLED: "gray",
    BroadcastStatus.FAILED: "red",
}


def campaign_usage(campaign: Campaign) -> dict[str, Any]:
    """Uso da campanha: SOMENTE números agregados (nenhum dado pessoal de apoiador)."""
    now = timezone.now()
    d7, d30 = now - timedelta(days=7), now - timedelta(days=30)

    voters = Voter.objects.filter(campaign=campaign).aggregate(
        total=Count("pk"),
        last7=Count("pk", filter=Q(created_at__gte=d7)),
        last30=Count("pk", filter=Q(created_at__gte=d30)),
        messageable=Count("pk", filter=MESSAGEABLE_Q),
        opted_out=Count("pk", filter=Q(opt_out_at__isnull=False)),
        geolocated=Count("pk", filter=Q(latitude__isnull=False, longitude__isnull=False)),
    )

    team = {role: {"active": 0, "inactive": 0} for role in (Role.ADMIN, Role.COORDENADOR, Role.CABO)}
    for row in User.objects.filter(campaign=campaign).order_by().values("role", "is_active").annotate(n=Count("pk")):
        if row["role"] in team:
            team[row["role"]]["active" if row["is_active"] else "inactive"] += row["n"]
    roles = [
        {"label": label_of(Role, role), "active": counts["active"], "inactive": counts["inactive"]}
        for role, counts in team.items()
    ]
    last_login = User.objects.filter(campaign=campaign).aggregate(last=Max("last_login"))["last"]

    connections = WhatsAppConnection.objects.filter(campaign=campaign).aggregate(
        total=Count("pk"), connected=Count("pk", filter=Q(status=ConnectionStatus.CONNECTED))
    )
    status_order = {value: i for i, value in enumerate(BroadcastStatus.values)}
    broadcast_rows = Broadcast.objects.filter(campaign=campaign).order_by().values("status").annotate(n=Count("pk"))
    broadcasts_by_status = [
        {"label": label_of(BroadcastStatus, row["status"]), "count": row["n"], "tone": BROADCAST_TONES.get(row["status"], "gray")}
        for row in sorted(broadcast_rows, key=lambda r: status_order.get(r["status"], 99))
    ]
    messages = BroadcastMessage.objects.filter(campaign=campaign).aggregate(
        sent=Count("pk", filter=Q(status__in=[MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ])),
        failed=Count("pk", filter=Q(status=MessageStatus.FAILED)),
    )

    return {
        "voters": voters,
        "team": roles,
        "team_total": sum(r["active"] + r["inactive"] for r in roles),
        "last_login": last_login,
        "connections": connections,
        "templates": MessageTemplate.objects.filter(campaign=campaign).count(),
        "dashboards": Dashboard.objects.filter(campaign=campaign).count(),
        "broadcasts_total": sum(r["count"] for r in broadcasts_by_status),
        "broadcasts_by_status": broadcasts_by_status,
        "messages": messages,
        "goal_percent": (voters["total"] / campaign.voter_goal * 100) if campaign.voter_goal else None,
        "messageable_percent": (voters["messageable"] / voters["total"] * 100) if voters["total"] else 0,
        "geolocated_percent": (voters["geolocated"] / voters["total"] * 100) if voters["total"] else 0,
    }


# ---------------------------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------------------------

# Chaves (minúsculas) que podem carregar dados pessoais de apoiadores
PERSONAL_KEYS = frozenset(
    k.lower()
    for k in (
        "name nome fullname phone telefone celular whatsapp email cpf rg birthdate birth_date nascimento street rua "
        "logradouro number numero complement complemento address endereco cep latitude longitude lat lng notes "
        "observacoes body renderedbody rendered_body fromphone from_phone electoralzone electoral_zone "
        "electoralsection electoral_section consentip consent_ip"
    ).split()
)
VOTER_ENTITIES = frozenset({"voter", "broadcastmessage", "inboundmessage"})
REDACTED = "•••"
_EMAIL_LIKE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_LIKE = re.compile(r"^[+\d\s().-]+$")


def is_voter_related(action: str, entity: str | None) -> bool:
    return (action or "").startswith("voter.") or (entity or "").lower() in VOTER_ENTITIES


def _looks_personal(value: str) -> bool:
    text = value.strip()
    if _EMAIL_LIKE.match(text):
        return True
    digits = re.sub(r"\D", "", text)
    return bool(_PHONE_LIKE.match(text)) and 10 <= len(digits) <= 13


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return REDACTED
    if isinstance(value, str):
        return REDACTED if _looks_personal(value) else value
    if isinstance(value, list):
        return [_redact(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: (REDACTED if str(k).lower() in PERSONAL_KEYS else _redact(v, depth + 1)) for k, v in value.items()}
    return value


def sanitize_audit_details(action: str, entity: str | None, details: Any) -> Any:
    """Detalhes prontos para o super admin: em eventos de apoiadores, mascara chaves/valores com dados pessoais."""
    if details is None:
        return None
    return _redact(details) if is_voter_related(action, entity) else details


def pretty_details(details: Any, limit: int = 4000) -> str:
    if details in (None, {}, []):
        return ""
    text = json.dumps(details, indent=2, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "\n…"


def audit_queryset(cleaned: dict[str, Any]) -> QuerySet:
    """Linhas de auditoria filtradas. Não junta apoiadores; só campanha e usuário (conta de equipe)."""
    qs = (
        AuditLog.objects.select_related("campaign", "user")
        .only(
            "id", "created_at", "action", "entity", "entity_id", "ip", "details",
            "campaign", "campaign__ballot_name", "user", "user__name", "user__role",
        )  # fmt: skip
        .order_by("-created_at", "-id")
    )
    campaign = cleaned.get("campaign") or ""
    if campaign == PLATFORM_SCOPE:
        qs = qs.filter(campaign__isnull=True)
    elif campaign:
        qs = qs.filter(campaign_id=campaign)
    if action := cleaned.get("action"):
        qs = qs.filter(action=action)
    if start := cleaned.get("start"):
        qs = qs.filter(created_at__gte=dt.datetime(start.year, start.month, start.day, tzinfo=SAO_PAULO))
    if end := cleaned.get("end"):
        limit = dt.datetime(end.year, end.month, end.day, tzinfo=SAO_PAULO) + timedelta(days=1)
        qs = qs.filter(created_at__lt=limit)
    return qs


def decorate_audit_rows(rows) -> list:
    """Rótulos e detalhes saneados para exibição (sem consultas extras)."""
    out = []
    for row in rows:
        row.action_label = action_label(row.action)
        row.user_role_label = label_of(Role, row.user.role) if row.user else ""
        row.entity_short_id = row.entity_id[:8] if row.entity_id else ""
        row.details_text = pretty_details(sanitize_audit_details(row.action, row.entity, row.details))
        out.append(row)
    return out
