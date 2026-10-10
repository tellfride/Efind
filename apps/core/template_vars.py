"""Variáveis dos modelos de mensagem ({{nome}}, {{bairro}}...) e renderização (lógica pura)."""

from __future__ import annotations

import re

from .utils import first_name

TEMPLATE_VARIABLES = [
    {"key": "nome", "label": "Nome completo do eleitor", "example": "Maria Aparecida da Silva"},
    {"key": "primeiro_nome", "label": "Primeiro nome do eleitor", "example": "Maria"},
    {"key": "bairro", "label": "Bairro do eleitor", "example": "Centro"},
    {"key": "cidade", "label": "Cidade do eleitor", "example": "Campinas"},
    {"key": "candidato", "label": "Nome de urna do candidato", "example": "Dr. João"},
    {"key": "numero", "label": "Número do candidato", "example": "12345"},
    {"key": "partido", "label": "Partido", "example": "PXX"},
    {"key": "cargo", "label": "Cargo disputado", "example": "Vereador(a)"},
    {"key": "cabo", "label": "Nome de quem cadastrou o eleitor", "example": "Carlos"},
]
VARIABLE_KEYS = [v["key"] for v in TEMPLATE_VARIABLES]
EXAMPLE_CONTEXT = {v["key"]: v["example"] for v in TEMPLATE_VARIABLES}

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")


def render_template(body: str, ctx: dict) -> str:
    """Substitui {{variavel}} pelo valor do contexto (variável desconhecida/vazia vira "")."""

    def repl(m: re.Match) -> str:
        v = ctx.get(m.group(1).lower())
        return "" if v is None else str(v)

    return _VAR_RE.sub(repl, body or "")


def extract_variables(body: str) -> list[str]:
    """Variáveis usadas num texto (ordem de aparição, sem repetição)."""
    out: list[str] = []
    for m in _VAR_RE.finditer(body or ""):
        k = m.group(1).lower()
        if k not in out:
            out.append(k)
    return out


def unknown_variables(body: str) -> list[str]:
    return [k for k in extract_variables(body) if k not in VARIABLE_KEYS]


def build_template_context(voter, campaign, registered_by=None) -> dict:
    """Contexto para renderizar um modelo para um eleitor. `campaign` e `voter` são instâncias dos models."""
    from .constants import Office, label_of

    return {
        "nome": voter.name,
        "primeiro_nome": first_name(voter.name),
        "bairro": voter.neighborhood or "",
        "cidade": voter.city or "",
        "candidato": campaign.ballot_name,
        "numero": campaign.ballot_number or "",
        "partido": campaign.party or "",
        "cargo": label_of(Office, campaign.office),
        "cabo": first_name(registered_by.name) if registered_by else "",
    }
