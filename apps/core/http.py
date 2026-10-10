"""Helpers de resposta (toasts via HTMX, erros JSON, downloads)."""

from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse


def with_toast(response: HttpResponse, message: str, level: str = "success") -> HttpResponse:
    """Dispara um toast no navegador em respostas HTMX (cabeçalho HX-Trigger)."""
    existing = response.headers.get("HX-Trigger")
    payload = json.loads(existing) if existing and existing.startswith("{") else {}
    payload["toast"] = {"message": message, "level": level}
    response["HX-Trigger"] = json.dumps(payload, ensure_ascii=False)
    return response


def json_error(message: str, status: int = 400, **extra) -> JsonResponse:
    return JsonResponse({"error": message, **extra}, status=status)


def csv_response(content: str, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
