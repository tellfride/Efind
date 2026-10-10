"""Gravação de eleitores vindos dos formulários (cadastro público e painel)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.constants import GeoStatus, VoterSource

from .forms import voter_data_from_cleaned
from .merge import DuplicateMergePlan, plan_duplicate_merge
from .models import Voter
from .public import PublicRegistration


@dataclass
class PublicRegisterResult:
    voter: Voter
    created: bool
    plan: DuplicateMergePlan | None = None  # só quando o telefone já existia
    source: str = VoterSource.LINK.value

    @property
    def needs_geocode(self) -> bool:
        return self.created or bool(self.plan and self.plan.needs_geocode)


def register_public_voter(
    reg: PublicRegistration, cleaned: dict[str, Any], *, ip: str | None, now: datetime
) -> PublicRegisterResult:
    """Cadastro pelo link público.

    - telefone novo na campanha: cria o eleitor vinculado ao dono do link, com o consentimento registrado;
    - telefone já cadastrado: NÃO revela nem sobrescreve nada; renova o consentimento, completa campos vazios
      e mantém quem cadastrou originalmente (veja `merge.plan_duplicate_merge`).
    """
    campaign = reg.campaign
    data = voter_data_from_cleaned(cleaned)
    consent_text = reg.consent_text
    opt_in = bool(cleaned.get("whatsapp_opt_in"))
    source = cleaned.get("source") or VoterSource.LINK.value

    with transaction.atomic():
        existing = Voter.objects.select_for_update().filter(campaign_id=campaign.pk, phone=data["phone"]).first()
        if existing is None:
            try:
                with transaction.atomic():
                    voter = Voter.objects.create(
                        campaign_id=campaign.pk,
                        registered_by=reg.owner,
                        source=source,
                        consent_at=now,
                        consent_ip=ip,
                        consent_text=consent_text,
                        whatsapp_opt_in=opt_in,
                        geo_status=GeoStatus.PENDING,
                        **data,
                    )
                return PublicRegisterResult(voter=voter, created=True, source=source)
            except IntegrityError:  # outro envio do mesmo telefone chegou primeiro
                existing = Voter.objects.select_for_update().filter(campaign_id=campaign.pk, phone=data["phone"]).first()
                if existing is None:
                    raise

        plan = plan_duplicate_merge(
            existing, data, whatsapp_opt_in=opt_in, consent_text=consent_text, consent_ip=ip, now=now
        )
        for key, value in plan.updates.items():
            setattr(existing, key, value)
        existing.save(update_fields=[*plan.updates, "updated_at"])
        return PublicRegisterResult(voter=existing, created=False, plan=plan, source=source)
