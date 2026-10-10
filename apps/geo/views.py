from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.core.ratelimit import rate_limit
from apps.core.utils import client_ip

from .cep import lookup_cep, normalize_cep


@require_GET
def cep_lookup(request, cep: str):
    """Consulta pública de CEP (formulário de cadastro e formulários do painel), com limite por IP."""
    normalized = normalize_cep(cep)
    if not normalized:
        return JsonResponse({"error": "CEP inválido"}, status=400)
    limit = rate_limit(f"cep:{client_ip(request)}", 60, 60)
    if not limit.ok:
        response = JsonResponse({"error": "Muitas consultas. Aguarde um instante."}, status=429)
        response["Retry-After"] = str(limit.retry_after_seconds)
        return response
    info = lookup_cep(normalized)
    if info is None:
        return JsonResponse({"error": "CEP não encontrado"}, status=404)
    response = JsonResponse(info.as_dict())
    response["Cache-Control"] = "public, max-age=86400"
    return response
