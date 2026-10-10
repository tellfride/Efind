"""Inicialização de uma campanha nova: permissões padrão por papel + dashboards-modelo.
Chamado pelo super admin ao criar a campanha e pelo seed (dentro de transaction.atomic)."""

from __future__ import annotations

from apps.accounts.models import RolePermission
from apps.core.constants import CONFIGURABLE_ROLES
from apps.core.permissions import MODULE_KEYS, default_permissions_for
from apps.dashboards.presets import create_default_dashboards


def bootstrap_campaign(campaign) -> None:
    rows = []
    for role in CONFIGURABLE_ROLES:
        perms = default_permissions_for(role)
        for module in MODULE_KEYS:
            rows.append(
                RolePermission(
                    campaign=campaign,
                    role=role,
                    module=module,
                    can_view=perms[module]["view"],
                    can_create=perms[module]["create"],
                    can_edit=perms[module]["edit"],
                    can_delete=perms[module]["delete"],
                    can_export=perms[module]["export"],
                )
            )
    RolePermission.objects.bulk_create(rows)
    create_default_dashboards(campaign)
