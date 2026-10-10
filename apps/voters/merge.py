"""Regras puras de atualização de eleitor: recadastro com telefone já existente e mudança de endereço."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apps.core.constants import GeoStatus
from apps.core.utils import normalize_text

# Campos que um recadastro pode completar (somente se estiverem vazios no cadastro existente)
FILLABLE_FIELDS = (
    "email",
    "birth_date",
    "gender",
    "cep",
    "street",
    "number",
    "complement",
    "neighborhood",
    "city",
    "state",
    "electoral_zone",
    "electoral_section",
)

# Campos que alteram a geocodificação (o número não entra: as coordenadas são do CEP/logradouro)
GEO_ADDRESS_FIELDS = ("cep", "street", "neighborhood", "city", "state")


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


@dataclass
class DuplicateMergePlan:
    """Atualizações (campo → valor) a gravar no eleitor existente."""

    updates: dict[str, Any]
    filled: list[str] = field(default_factory=list)  # campos completados com dados novos
    needs_geocode: bool = False


def plan_duplicate_merge(
    existing: Any,
    incoming: dict[str, Any],
    *,
    whatsapp_opt_in: bool,
    consent_text: str,
    consent_ip: str | None,
    now: datetime,
) -> DuplicateMergePlan:
    """Recadastro pelo link com telefone já cadastrado na campanha.

    - nunca sobrescreve dados existentes (só completa campos vazios) e mantém quem cadastrou;
    - renova o consentimento LGPD (data, IP e texto);
    - reativa o WhatsApp (opt-in e remove o descadastro) SOMENTE se a caixa foi marcada agora.

    `existing` é qualquer objeto com os atributos dos campos (normalmente um Voter).
    """
    updates: dict[str, Any] = {"consent_at": now, "consent_ip": consent_ip, "consent_text": consent_text}
    filled: list[str] = []
    for key in FILLABLE_FIELDS:
        if is_empty(getattr(existing, key, None)) and not is_empty(incoming.get(key)):
            updates[key] = incoming[key]
            filled.append(key)
    if whatsapp_opt_in:
        updates["whatsapp_opt_in"] = True
        updates["opt_out_at"] = None
    needs_geocode = any(k in GEO_ADDRESS_FIELDS for k in filled)
    if needs_geocode:
        updates.update(geo_status=GeoStatus.PENDING, latitude=None, longitude=None)
    return DuplicateMergePlan(updates=updates, filled=filled, needs_geocode=needs_geocode)


def _normalize_for_compare(value: Any) -> str:
    return " ".join(normalize_text("" if value is None else str(value)).split())


def geo_address_changed(before: Any, after: dict[str, Any]) -> bool:
    """O endereço relevante para o mapa mudou? (ignora diferenças de caixa, acentos e espaços)"""
    return any(
        _normalize_for_compare(getattr(before, k, "")) != _normalize_for_compare(after.get(k, ""))
        for k in GEO_ADDRESS_FIELDS
    )
