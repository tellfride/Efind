"""Registro de auditoria. Nunca lança erro (auditoria não pode derrubar a operação principal)."""

from __future__ import annotations

import logging
from typing import Any

from apps.core.utils import client_ip

logger = logging.getLogger(__name__)


def audit(
    action: str,
    *,
    request=None,
    user=None,
    campaign=None,
    campaign_id=None,
    entity: str = "",
    entity_id: Any = "",
    details: dict | None = None,
    ip: str | None = None,
) -> None:
    """Grava uma linha de auditoria.

    - `request`: se informado, usa request.user (quando `user` não for passado) e o IP do cliente.
    - Fora de requisições (worker/comandos), passe user/campaign explicitamente.
    - `details` deve ser JSON simples e SEM dados pessoais (telefone, e-mail, nome); use ids e contagens.
    """
    from .models import AuditLog

    try:
        if user is None and request is not None and getattr(request.user, "is_authenticated", False):
            user = request.user
        if campaign_id is None:
            campaign_id = campaign.pk if campaign is not None else getattr(user, "campaign_id", None)
        if ip is None and request is not None:
            ip = client_ip(request)
        AuditLog.objects.create(
            action=action,
            user=user if getattr(user, "pk", None) else None,
            campaign_id=campaign_id,
            entity=entity or "",
            entity_id=str(entity_id) if entity_id else "",
            details=details or None,
            ip=ip or None,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao registrar auditoria: %s", action)
