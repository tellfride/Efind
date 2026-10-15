"""Regras puras da trilha de auditoria da campanha: leitura segura dos filtros, rótulos e formatação.

Nada aqui acessa o banco: as consultas (sempre restritas à campanha e à rede do usuário) ficam em `services.py`.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from apps.auditlog.actions import AUDIT_ACTIONS
from apps.core.utils import normalize_text

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
AUDIT_PAGE_SIZE = 50
AUDIT_EXPORT_LIMIT = 50_000  # linhas por exportação CSV

# Ações registradas por este módulo que ainda não constam em apps.auditlog.actions
EXTRA_AUDIT_LABELS = {"audit.export": "Auditoria exportada"}
AUDIT_LABELS: dict[str, str] = {**AUDIT_ACTIONS, **EXTRA_AUDIT_LABELS}

_ACTION_RE = re.compile(r"[a-z0-9_]+(\.[a-z0-9_]+)*")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class AuditFilters:
    """Filtros já validados. Nunca ampliam o escopo: a consulta sempre inclui a campanha e a rede do usuário."""

    user_id: str | None = None
    action: str | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None

    @property
    def active(self) -> bool:
        return any((self.user_id, self.action, self.date_from, self.date_to))

    def to_params(self) -> dict[str, str]:
        """Parâmetros de URL canônicos (paginação e exportação)."""
        params: dict[str, str] = {}
        if self.user_id:
            params["user"] = self.user_id
        if self.action:
            params["action"] = self.action
        if self.date_from:
            params["from"] = self.date_from.isoformat()
        if self.date_to:
            params["to"] = self.date_to.isoformat()
        return params

    def audit_details(self) -> dict[str, str]:
        """Resumo dos filtros para a própria auditoria da exportação (somente ids, ação e datas)."""
        return self.to_params()


def _first(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip()


def parse_iso_date(value: str | None) -> dt.date | None:
    """AAAA-MM-DD válida no calendário (2000–2100); caso contrário None."""
    if not value or not _ISO_DATE_RE.fullmatch(value):
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if 2000 <= parsed.year <= 2100 else None


def parse_audit_filters(
    params: Mapping[str, Any],
    allowed_user_ids: Collection[str] | None = None,
    allowed_actions: Collection[str] | None = None,
) -> AuditFilters:
    """Lê os filtros da querystring descartando qualquer valor inválido ou fora das listas permitidas."""
    user_id = None
    raw_user = _first(params, "user")
    if raw_user:
        try:
            candidate = str(uuid.UUID(raw_user))
        except ValueError:
            candidate = None
        if candidate and (allowed_user_ids is None or candidate in allowed_user_ids):
            user_id = candidate

    action = _first(params, "action")
    if not (action and _ACTION_RE.fullmatch(action) and (allowed_actions is None or action in allowed_actions)):
        action = None

    date_from = parse_iso_date(_first(params, "from"))
    date_to = parse_iso_date(_first(params, "to"))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    return AuditFilters(user_id=user_id, action=action or None, date_from=date_from, date_to=date_to)


def created_range(filters: AuditFilters) -> tuple[dt.datetime | None, dt.datetime | None]:
    """Intervalo [início, fim) em horário de Brasília para `created_at` (fim = início do dia seguinte)."""
    start = dt.datetime.combine(filters.date_from, dt.time.min, tzinfo=SAO_PAULO) if filters.date_from else None
    end = (
        dt.datetime.combine(filters.date_to + dt.timedelta(days=1), dt.time.min, tzinfo=SAO_PAULO)
        if filters.date_to
        else None
    )
    return start, end


# --- Rótulos ------------------------------------------------------------------------------------------
AUDIT_CATEGORY_LABELS = {
    "auth": "Acesso",
    "campaign": "Campanha",
    "settings": "Configurações",
    "user": "Equipe",
    "permissions": "Equipe",
    "voter": "Apoiadores",
    "template": "Modelos de mensagem",
    "broadcast": "Disparos",
    "whatsapp": "WhatsApp",
    "dashboard": "Dashboards",
    "audit": "Auditoria",
}


def audit_category(action: str) -> str:
    return AUDIT_CATEGORY_LABELS.get(action.split(".")[0], "Outras")


def audit_action_label(action: str) -> str:
    """Rótulo legível; ações desconhecidas viram "Categoria: verbo"."""
    if action in AUDIT_LABELS:
        return AUDIT_LABELS[action]
    verb = " ".join(action.split(".")[1:]).replace("_", " ").strip()
    return f"{audit_category(action)}: {verb}" if verb else action


def group_audit_actions(actions: Collection[str]) -> list[dict[str, Any]]:
    """Agrupa ações por categoria (para <optgroup>), sem repetição, ordenadas por rótulo (sem considerar acentos)."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for action in sorted(set(actions)):
        groups.setdefault(audit_category(action), []).append((action, audit_action_label(action)))
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == "Outras", normalize_text(kv[0])))
    return [
        {"label": label, "options": sorted(options, key=lambda o: normalize_text(o[1]))} for label, options in ordered
    ]


_ENTITY_LABELS = {
    "voter": "Apoiador",
    "user": "Usuário",
    "campaign": "Campanha",
    "messagetemplate": "Modelo de mensagem",
    "template": "Modelo de mensagem",
    "broadcast": "Disparo",
    "whatsappconnection": "Conexão de WhatsApp",
    "connection": "Conexão de WhatsApp",
    "dashboard": "Dashboard",
    "rolepermission": "Permissões",
    "userpermission": "Permissões",
    "permission": "Permissões",
    "permissions": "Permissões",
    "auditlog": "Auditoria",
}


def audit_entity_label(entity: str | None) -> str:
    if not entity:
        return ""
    return _ENTITY_LABELS.get(re.sub(r"[^a-z]", "", entity.lower()), entity)


def format_audit_details(details: Any) -> str | None:
    """JSON legível dos detalhes (None quando não há nada a mostrar)."""
    if details is None or details == {} or details == []:
        return None
    try:
        return json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(details)


def export_filename(filters: AuditFilters, today: dt.date) -> str:
    """auditoria_AAAA-MM-DD[_DE_a_ATE].csv"""
    range_part = ""
    if filters.date_from or filters.date_to:
        range_part = f"_{filters.date_from.isoformat() if filters.date_from else 'inicio'}_a_"
        range_part += filters.date_to.isoformat() if filters.date_to else "hoje"
    return f"auditoria_{today.isoformat()}{range_part}.csv"
