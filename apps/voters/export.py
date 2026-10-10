"""Exportação de eleitores em CSV: colunas e conversão de cada registro (pura, sem banco)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.core.constants import Gender, SupportLevel, VoterSource, label_of
from apps.core.phone import format_phone
from apps.core.utils import age_from, parse_tags

from .utils import WHATSAPP_STATUS_LABELS, whatsapp_status_of

MAX_EXPORT_ROWS = 50_000

# (chave, rótulo) — formato esperado por apps.core.utils.to_csv
EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("nome", "Nome"),
    ("whatsapp", "WhatsApp"),
    ("email", "E-mail"),
    ("nascimento", "Nascimento"),
    ("idade", "Idade"),
    ("genero", "Gênero"),
    ("cep", "CEP"),
    ("rua", "Logradouro"),
    ("numero", "Número"),
    ("complemento", "Complemento"),
    ("bairro", "Bairro"),
    ("cidade", "Cidade"),
    ("uf", "UF"),
    ("zona", "Zona eleitoral"),
    ("secao", "Seção eleitoral"),
    ("apoio", "Nível de apoio"),
    ("tags", "Tags"),
    ("origem", "Origem"),
    ("cadastrado_por", "Cadastrado por"),
    ("situacao_whatsapp", "Situação WhatsApp"),
    ("consentimento", "Consentimento LGPD em"),
    ("cadastrado_em", "Cadastrado em"),
    ("observacoes", "Observações"),
]


def _format_cep(cep: str) -> str:
    d = "".join(c for c in cep or "" if c.isdigit())
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (cep or "")


def _format_dt(value: datetime | None) -> str:
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d/%m/%Y %H:%M")


def voter_to_export_row(voter: Any, today=None) -> dict[str, Any]:
    """Uma linha do CSV (rótulos em pt-BR, datas no fuso de São Paulo). A proteção contra injeção de
    fórmulas (=, +, -, @) é aplicada por apps.core.utils.to_csv na escrita de cada célula."""
    registered_by = getattr(voter, "registered_by", None)
    return {
        "nome": voter.name,
        "whatsapp": format_phone(voter.phone),
        "email": voter.email,
        "nascimento": voter.birth_date.strftime("%d/%m/%Y") if voter.birth_date else "",
        "idade": age_from(voter.birth_date, today) if voter.birth_date else "",
        "genero": label_of(Gender, voter.gender) if voter.gender else "",
        "cep": _format_cep(voter.cep),
        "rua": voter.street,
        "numero": voter.number,
        "complemento": voter.complement,
        "bairro": voter.neighborhood,
        "cidade": voter.city,
        "uf": voter.state,
        "zona": voter.electoral_zone,
        "secao": voter.electoral_section,
        "apoio": label_of(SupportLevel, voter.support_level) if voter.support_level else "",
        "tags": ", ".join(parse_tags(voter.tags)),
        "origem": label_of(VoterSource, voter.source),
        "cadastrado_por": registered_by.name if registered_by else "",
        "situacao_whatsapp": WHATSAPP_STATUS_LABELS[whatsapp_status_of(voter)],
        "consentimento": _format_dt(voter.consent_at),
        "cadastrado_em": _format_dt(voter.created_at),
        "observacoes": voter.notes,
    }


def export_filename(today=None) -> str:
    day = today or timezone.localdate()
    return f"eleitores-{day.isoformat()}.csv"


def audit_safe_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    """Filtros para a trilha de auditoria SEM dados pessoais: o termo de busca (nome/telefone/e-mail) é omitido."""
    out = dict(filters or {})
    if "q" in out:
        out["q"] = "(busca por texto)"
    return out
