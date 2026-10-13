"""Importação de eleitores por CSV: página, pré-visualização (JSON, validada no servidor), gravação e resultado."""

from __future__ import annotations

import json

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.auditlog.service import audit
from apps.core.decorators import module_permission_required
from apps.core.http import csv_response, json_error
from apps.core.ratelimit import rate_limit
from apps.core.utils import client_ip

from .csv_import import (
    COLUMN_GUIDE,
    IMPORT_FIELDS,
    MAX_IMPORT_ROWS,
    CsvParseError,
    build_template_csv,
)
from .forms import ImportForm
from .import_service import (
    PREVIEW_ROWS,
    ImportAnalysis,
    analyze_import,
    n_columns_of,
    run_import,
)
from .utils import safe_ip

RESULT_SESSION_KEY = "voters_import_result"
CLIENT_MAX_CHARS = 1_500_000  # limite do navegador (o corpo da requisição tem teto no servidor)
STATUS_LABELS = {
    "ok": "Será importado",
    "invalid": "Inválido",
    "duplicate_file": "Telefone repetido no arquivo",
    "duplicate_campaign": "Já cadastrado",
}


def _field_defs() -> list[dict]:
    return [{"key": f.key, "label": f.label, "required": f.required} for f in IMPORT_FIELDS]


def _labels(keys) -> list[str]:
    by_key = {f.key: f.label for f in IMPORT_FIELDS}
    return [by_key[k] for k in keys]


def analysis_payload(analysis: ImportAnalysis) -> dict:
    """Resposta JSON da pré-visualização (tudo calculado no servidor)."""
    parsed = analysis.parsed
    n_cols = n_columns_of(parsed)
    header_row = parsed.rows[0] if analysis.has_header else []
    sample_row = parsed.rows[1 if analysis.has_header else 0] if len(parsed.rows) > (1 if analysis.has_header else 0) else []
    columns = [
        {
            "index": i,
            "header": (header_row[i] if i < len(header_row) and header_row[i] else f"Coluna {i + 1}"),
            "sample": (sample_row[i] if i < len(sample_row) else "")[:60],
        }
        for i in range(n_cols)
    ]
    data_rows = len(parsed.rows) - (1 if analysis.has_header else 0)
    payload = {
        "ok": True,
        "separator": parsed.separator,
        "has_header": analysis.has_header,
        "columns": columns,
        "mapping": analysis.mapping,
        "total_rows": data_rows,
        "max_rows": MAX_IMPORT_ROWS,
        "over_limit": analysis.over_limit,
        "missing_required": _labels(analysis.missing_required),
        "ready": False,
    }
    if analysis.missing_required or analysis.over_limit:
        return payload

    used = [(i, key) for i, key in enumerate(analysis.mapping) if key]
    payload["fields_used"] = _labels([key for _, key in used])
    rows = []
    for result, record in zip(analysis.results[:PREVIEW_ROWS], analysis.records[:PREVIEW_ROWS], strict=False):
        status = analysis.status_of(result)
        rows.append(
            {
                "row": result.row,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "cells": [record.values.get(key, "") for _, key in used],
                "errors": result.errors,
                "warnings": result.warnings,
            }
        )
    payload["preview"] = rows
    payload["summary"] = {
        "valid": len(analysis.unique),
        "invalid": len(analysis.invalid),
        "repeated_in_file": len(analysis.repeated),
        "already_registered": len(analysis.already_registered),
        "will_import": len(analysis.to_import),
        "with_warnings": sum(1 for r in analysis.results if r.voter is not None and r.warnings),
    }
    payload["ready"] = bool(analysis.to_import)
    return payload


@module_permission_required("eleitores", "create", json_response=True)
@never_cache
@require_POST
def import_preview(request):
    """Lê o CSV enviado (texto) e devolve cabeçalhos, mapeamento e as 10 primeiras linhas validadas."""
    user = request.user
    if not rate_limit(f"voter-import-preview:{user.pk}", 90, 60).ok:
        return json_error("Muitas análises seguidas. Aguarde um instante.", 429)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return json_error("Requisição inválida.")
    if not isinstance(body, dict) or not isinstance(body.get("csv_text"), str):
        return json_error("Requisição inválida.")
    mapping = body.get("mapping")
    has_header = body.get("has_header")
    if (mapping is not None and not isinstance(mapping, list)) or (has_header is not None and not isinstance(has_header, bool)):
        return json_error("Requisição inválida.")
    try:
        analysis = analyze_import(body["csv_text"], user.campaign_id, mapping=mapping, has_header=has_header)
    except CsvParseError as exc:
        return json_error(str(exc))
    except ValueError as exc:
        return json_error(str(exc))
    return JsonResponse(analysis_payload(analysis))


def _page_context(form: ImportForm, initial: dict) -> dict:
    return {
        "form": form,
        "import_config": {
            "previewUrl": reverse("voters:import_preview"),
            "fields": _field_defs(),
            "maxChars": CLIENT_MAX_CHARS,
            "maxRows": MAX_IMPORT_ROWS,
            "initial": initial,
        },
        "max_rows": MAX_IMPORT_ROWS,
        "column_guide": COLUMN_GUIDE,
    }


@module_permission_required("eleitores", "create")
@require_GET
def import_template(request):
    """Modelo de planilha (CSV) para download. Servido pelo servidor (e não gerado no navegador) para funcionar também
    em navegadores embutidos, como o do WhatsApp, que costumam bloquear downloads por blob:."""
    return csv_response(build_template_csv(), "modelo-importacao-eleitores.csv")


@module_permission_required("eleitores", "create")
@never_cache
def voter_import(request):
    user = request.user
    initial = {"text": "", "mapping": None, "hasHeader": None}
    if request.method != "POST":
        return render(request, "voters/import.html", _page_context(ImportForm(user=user), initial))

    form = ImportForm(request.POST, user=user)
    raw_mapping = None
    try:
        raw_mapping = json.loads(request.POST.get("mapping") or "null")
    except ValueError:
        form.add_error(None, "Mapeamento de colunas inválido. Reenvie o arquivo.")
    initial = {
        "text": request.POST.get("csv_text", "")[:2_000_000],
        "mapping": raw_mapping if isinstance(raw_mapping, list) else None,
        "hasHeader": bool(request.POST.get("has_header")),
    }
    if form.is_valid():
        registrar = form.cleaned_data.get("registered_by") or user
        opt_in = bool(form.cleaned_data.get("whatsapp_opt_in"))
        analysis = None
        try:
            analysis = analyze_import(
                form.cleaned_data["csv_text"],
                user.campaign_id,
                mapping=raw_mapping,
                has_header=bool(form.cleaned_data.get("has_header")),
            )
        except (CsvParseError, ValueError) as exc:
            form.add_error(None, str(exc))
        if analysis is not None:
            if analysis.missing_required:
                form.add_error(None, "Associe as colunas obrigatórias: " + ", ".join(_labels(analysis.missing_required)) + ".")
            elif analysis.over_limit:
                form.add_error(None, f"O arquivo tem linhas demais. O máximo por importação é {MAX_IMPORT_ROWS:,}.".replace(",", "."))
            elif not analysis.to_import:
                form.add_error(None, "Nenhum eleitor novo para importar. Confira os avisos da pré-visualização.")
            else:
                with transaction.atomic():
                    outcome = run_import(
                        analysis,
                        campaign_id=user.campaign_id,
                        registered_by=registrar,
                        whatsapp_opt_in=opt_in,
                        now=timezone.now(),
                        ip=safe_ip(client_ip(request)),
                    )
                audit(
                    "voter.import",
                    request=request,
                    entity="Voter",
                    details={
                        "total": outcome.total,
                        "imported": outcome.imported,
                        "duplicates": outcome.duplicates_campaign + outcome.duplicates_file,
                        "invalid": outcome.invalid,
                        "whatsapp_opt_in": opt_in,
                        "registered_by": str(registrar.pk),
                    },
                )
                request.session[RESULT_SESSION_KEY] = outcome.as_session()
                return redirect("voters:import_result")
    return render(request, "voters/import.html", _page_context(form, initial))


@module_permission_required("eleitores", "create")
@never_cache
@require_GET
def voter_import_result(request):
    result = request.session.pop(RESULT_SESSION_KEY, None)
    if not result:
        messages.info(request, "Nenhuma importação recente para exibir.")
        return redirect("voters:import")
    for problem in result.get("problems", []):
        problem["label"] = STATUS_LABELS.get(problem.get("kind"), "")
    ignored = result["duplicates_campaign"] + result["duplicates_file"] + result["invalid"]
    return render(
        request,
        "voters/import_result.html",
        {"result": result, "ignored": ignored, "truncated": len(result.get("problems", [])) < ignored},
    )
