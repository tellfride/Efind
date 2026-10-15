"""Dashboards-modelo. Contrato: create_default_dashboards(campaign) é chamado por bootstrap_campaign
(criação da campanha e seed). Os modelos também servem de ponto de partida em "Novo dashboard".

Widget = {"id": str, "type": str, "size": "sm"|"md"|"lg"|"full", "config": {...}}
(config aceita: period 7|30|90|365, limit, filters (apps.core.voter_filters), text)
"""

from __future__ import annotations

import copy

from .models import Dashboard

DASHBOARD_PRESET_KEYS = ("visao_geral", "equipe", "territorial", "comunicacao")


def _w(id_: str, type_: str, size: str, **config) -> dict:
    return {"id": id_, "type": type_, "size": size, "config": config}


DASHBOARD_PRESETS: dict[str, dict] = {
    "visao_geral": {
        "name": "Visão geral",
        "description": "Principais números da campanha e o ranking de cadastros por cabo eleitoral.",
        "widgets": [
            _w("vg-total", "kpi_total", "sm"),
            _w("vg-hoje", "kpi_today", "sm"),
            _w("vg-periodo", "kpi_period", "sm", period=30),
            _w("vg-meta", "kpi_goal", "sm"),
            _w("vg-ranking", "ranking_members", "full", period=30, limit=10),
            _w("vg-evolucao", "timeline", "lg", period=30),
            _w("vg-whatsapp", "kpi_messageable", "sm"),
            _w("vg-bairros", "by_neighborhood", "md", limit=10),
            _w("vg-apoio", "by_support", "md"),
            _w("vg-recentes", "recent_voters", "full", limit=8),
        ],
    },
    "equipe": {
        "name": "Desempenho da equipe",
        "description": "Ranking semanal dos cabos eleitorais, coordenadores e metas individuais.",
        "widgets": [
            _w("eq-equipe", "kpi_team", "sm", period=7),
            _w("eq-hoje", "kpi_today", "sm"),
            _w("eq-semana", "kpi_period", "sm", period=7),
            _w("eq-meta", "kpi_goal", "sm"),
            _w("eq-ranking", "ranking_members", "full", period=7, limit=20),
            _w("eq-coord", "ranking_coordinators", "full", period=30, limit=10),
            _w("eq-metas", "goals_progress", "md", limit=10),
            _w("eq-evolucao", "timeline", "md", period=30),
        ],
    },
    "territorial": {
        "name": "Territorial",
        "description": "Onde estão os apoiadores: bairros, cidades e perfil da base.",
        "widgets": [
            _w("te-total", "kpi_total", "sm"),
            _w("te-periodo", "kpi_period", "sm", period=30),
            _w("te-whatsapp", "kpi_messageable", "sm"),
            _w("te-meta", "kpi_goal", "sm"),
            _w("te-bairros", "by_neighborhood", "md", limit=15),
            _w("te-cidades", "by_city", "md", limit=10),
            _w("te-idade", "by_age", "md"),
            _w("te-genero", "by_gender", "md"),
        ],
    },
    "comunicacao": {
        "name": "Comunicação (WhatsApp)",
        "description": "Base apta a receber mensagens e resultados dos disparos.",
        "widgets": [
            _w("co-whatsapp", "kpi_messageable", "sm"),
            _w("co-total", "kpi_total", "sm"),
            _w("co-periodo", "kpi_period", "sm", period=30),
            _w("co-hoje", "kpi_today", "sm"),
            _w("co-disparos", "broadcasts", "full", period=30),
            _w("co-apoio", "by_support", "md"),
            _w("co-origem", "by_source", "md"),
        ],
    },
}


def preset_widgets(key: str) -> list[dict]:
    """Cópia profunda dos widgets de um modelo."""
    return copy.deepcopy(DASHBOARD_PRESETS[key]["widgets"])


def create_default_dashboards(campaign) -> None:
    """Cria os dashboards-modelo (compartilhados, sem dono) de uma campanha recém-criada."""
    for key in DASHBOARD_PRESET_KEYS:
        preset = DASHBOARD_PRESETS[key]
        Dashboard.objects.create(
            campaign=campaign,
            owner=None,
            name=preset["name"],
            description=preset["description"],
            shared=True,
            is_default=(key == "visao_geral"),
            widgets=preset_widgets(key),
        )
