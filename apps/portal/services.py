"""Consultas da trilha de auditoria da campanha e gravação das configurações.

Regra de ouro: a campanha vem SEMPRE do usuário logado (`request.campaign`), nunca de parâmetros do cliente.
ADMIN vê a campanha inteira; os demais papéis (se receberem `auditoria.view`) veem só as ações da própria rede.
"""

from __future__ import annotations

import json
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.auditlog.models import AuditLog
from apps.auditlog.service import audit
from apps.core.access import scope_user_ids, team_scope
from apps.core.constants import Role, label_of, parse_form_config
from apps.core.utils import normalize_text

from .audit_rules import (
    AUDIT_EXPORT_LIMIT,
    AUDIT_LABELS,
    AuditFilters,
    audit_action_label,
    audit_entity_label,
    created_range,
    format_audit_details,
    group_audit_actions,
    parse_audit_filters,
)
from .settings_rules import changed_fields

# Campos de Campaign editados em cada cartão de configurações (nomes registrados na auditoria)
IDENTITY_FIELDS = (
    "candidate_name",
    "ballot_name",
    "ballot_number",
    "party",
    "office",
    "city",
    "state",
    "election_year",
    "voter_goal",
    "primary_color",
    "logo_url",
    "banner_url",
)
PUBLIC_FORM_FIELDS = ("form_title", "form_message", "form_config", "consent_text", "privacy_contact")


# --- Auditoria ----------------------------------------------------------------------------------------
def audit_queryset(campaign, user) -> QuerySet:
    """Linhas de auditoria visíveis ao usuário: campanha dele AND (campanha inteira se ADMIN, senão a rede dele)."""
    qs = AuditLog.objects.filter(campaign_id=campaign.pk)
    user_ids = scope_user_ids(user)
    if user_ids is not None:
        qs = qs.filter(user_id__in=user_ids)
    return qs


def audit_filter_options(campaign, user) -> dict[str, Any]:
    """Opções do formulário de filtros + listas permitidas (para descartar valores forjados na URL)."""
    members = list(team_scope(user).filter(campaign_id=campaign.pk).only("id", "name", "role", "is_active"))
    present = audit_queryset(campaign, user).order_by().values_list("action", flat=True).distinct()
    actions = sorted(set(AUDIT_LABELS) | set(present))
    return {
        "users": [
            {"id": str(m.pk), "name": m.name, "role": label_of(Role, m.role), "active": m.is_active}
            for m in sorted(members, key=lambda m: normalize_text(m.name))
        ],
        "action_groups": group_audit_actions(actions),
        "allowed_user_ids": {str(m.pk) for m in members},
        "allowed_actions": set(actions),
        "scoped": scope_user_ids(user) is not None,
    }


def read_audit_filters(params, options: dict[str, Any]) -> AuditFilters:
    return parse_audit_filters(params, options["allowed_user_ids"], options["allowed_actions"])


def apply_audit_filters(qs: QuerySet, filters: AuditFilters) -> QuerySet:
    """Aplica os filtros (AND com o escopo já presente em `qs`; nunca o ampliam)."""
    if filters.user_id:
        qs = qs.filter(user_id=filters.user_id)
    if filters.action:
        qs = qs.filter(action=filters.action)
    start, end = created_range(filters)
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lt=end)
    return qs


def with_users(qs: QuerySet) -> QuerySet:
    """Carrega o usuário de cada linha (sem N+1) e ordena do mais recente para o mais antigo."""
    return qs.select_related("user").only(
        "id", "created_at", "action", "entity", "entity_id", "ip", "details", "user__name", "user__role"
    ).order_by("-created_at", "-id")


def audit_row(log: AuditLog) -> dict[str, Any]:
    user = log.user
    return {
        "id": str(log.pk),
        "created_at": log.created_at,
        "action": log.action,
        "action_label": audit_action_label(log.action),
        "user_name": user.name if user else "",
        "user_role": label_of(Role, user.role) if user else "",
        "by_platform": bool(user and user.role == Role.SUPER_ADMIN),
        "entity": audit_entity_label(log.entity),
        "entity_id": log.entity_id,
        "ip": log.ip or "",
        "details": format_audit_details(log.details),
    }


AUDIT_CSV_COLUMNS = [
    ("data_hora", "Data/hora (Brasília)"),
    ("usuario", "Usuário"),
    ("papel", "Papel"),
    ("acao", "Ação"),
    ("codigo_acao", "Código da ação"),
    ("entidade", "Entidade"),
    ("id_entidade", "ID da entidade"),
    ("ip", "IP"),
    ("detalhes", "Detalhes (JSON)"),
]


def audit_csv_rows(qs: QuerySet) -> tuple[list[dict[str, Any]], bool]:
    """Linhas do CSV (até AUDIT_EXPORT_LIMIT) e se a exportação foi truncada."""
    logs = list(with_users(qs)[: AUDIT_EXPORT_LIMIT + 1])
    truncated = len(logs) > AUDIT_EXPORT_LIMIT
    rows = []
    for log in logs[:AUDIT_EXPORT_LIMIT]:
        row = audit_row(log)
        if row["by_platform"]:
            who = f"{row['user_name']} (suporte E-Find)"
        else:
            who = row["user_name"] or "Sistema / apoiador"
        rows.append(
            {
                "data_hora": timezone.localtime(log.created_at).strftime("%d/%m/%Y %H:%M:%S"),
                "usuario": who,
                "papel": row["user_role"],
                "acao": row["action_label"],
                "codigo_acao": row["action"],
                "entidade": row["entity"],
                "id_entidade": row["entity_id"],
                "ip": row["ip"],
                "detalhes": "" if log.details in (None, {}, []) else json.dumps(log.details, ensure_ascii=False, sort_keys=True, default=str),
            }
        )
    return rows, truncated


# --- Configurações ------------------------------------------------------------------------------------
def current_values(campaign, fields: tuple[str, ...]) -> dict[str, Any]:
    """Valores atuais da campanha (form_config já mesclado com o padrão) para comparar com os novos."""
    values = {name: getattr(campaign, name) for name in fields}
    if "form_config" in values:
        values["form_config"] = parse_form_config(values["form_config"])
    return values


def save_campaign_settings(request, campaign, new_values: dict[str, Any], *, section: str, fields: tuple[str, ...]):
    """Grava só o que mudou e audita `settings.update` com os NOMES dos campos alterados.

    Devolve a lista de campos alterados (vazia = nada a salvar, nada é gravado nem auditado).
    """
    changed = changed_fields(current_values(campaign, fields), new_values)
    if not changed:
        return []
    for name in changed:
        setattr(campaign, name, new_values[name])
    campaign.save(update_fields=[*changed, "updated_at"])
    audit(
        "settings.update",
        request=request,
        campaign=campaign,
        entity="Campaign",
        entity_id=campaign.pk,
        details={"section": section, "fields": changed},
    )
    return changed
