"""Operações de escrita do super admin. Cada função é atômica e audita; as views só validam e respondem.

Senhas provisórias NUNCA são gravadas em sessão, banco ou auditoria: ficam apenas no objeto `IssuedCredentials`
devolvido, que a view renderiza diretamente na resposta do POST (uma única vez).
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, RestrictedError
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import email_in_use
from apps.auditlog.service import audit
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import BroadcastStatus, CampaignStatus, Role
from apps.core.qr import app_url
from apps.core.utils import slugify
from apps.messaging.models import Broadcast
from apps.voters.models import Voter

SLUG_MAX_LENGTH = 60
SLUG_SUFFIX_RESERVE = 6  # espaço para "-99999" sem estourar o limite
VOTER_DELETE_CHUNK = 500  # eleitores apagados por consulta na exclusão de uma campanha

_PASSWORD_LETTERS = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"  # sem caracteres ambíguos (i, l, o, I, O)
_PASSWORD_DIGITS = "23456789"


class ServiceError(Exception):
    """Falha de regra de negócio com mensagem pronta para o usuário (pt-BR)."""


class EmailAlreadyUsed(ServiceError):
    def __init__(self):
        super().__init__("Este e-mail já está cadastrado no E-Find. Use outro.")


@dataclass(frozen=True)
class IssuedCredentials:
    """Credenciais exibidas uma única vez (criação de conta ou redefinição de senha)."""

    name: str
    email: str
    password: str
    generated: bool
    login_url: str

    @property
    def password_label(self) -> str:
        return "Senha provisória" if self.generated else "Senha"

    @property
    def copy_all(self) -> str:
        return "\n".join(
            [
                "Acesso ao E-Find",
                f"Endereço: {self.login_url}",
                f"E-mail: {self.email}",
                f"{self.password_label}: {self.password}",
            ]
        )


# ---------------------------------------------------------------------------------------------
# Lógica pura
# ---------------------------------------------------------------------------------------------


def generate_temp_password() -> str:
    """Senha provisória legível: 8 letras + 2 dígitos (gerada com `secrets`)."""
    letters = "".join(secrets.choice(_PASSWORD_LETTERS) for _ in range(8))
    digits = "".join(secrets.choice(_PASSWORD_DIGITS) for _ in range(2))
    return letters + digits


def campaign_slug_base(ballot_name: str) -> str:
    """Base do identificador a partir do nome de urna; "campanha" se não sobrar nenhum caractere válido."""
    return slugify(ballot_name, SLUG_MAX_LENGTH - SLUG_SUFFIX_RESERVE) or "campanha"


def unique_slug(base: str, existing: Iterable[str]) -> str:
    """Primeiro identificador livre da sequência: base, base-2, base-3..."""
    taken = set(existing)
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def new_campaign_slug(ballot_name: str) -> str:
    base = campaign_slug_base(ballot_name)
    return unique_slug(base, Campaign.objects.filter(slug__startswith=base).values_list("slug", flat=True))


def _credentials(user: User, password: str, generated: bool) -> IssuedCredentials:
    return IssuedCredentials(
        name=user.name, email=user.email, password=password, generated=generated, login_url=app_url("/login/")
    )


def _issue_password(explicit: str) -> tuple[str, bool]:
    return (explicit, False) if explicit else (generate_temp_password(), True)


# ---------------------------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------------------------


def create_campaign_with_admin(request, *, campaign_data: dict, admin_data: dict) -> tuple[Campaign, User, IssuedCredentials]:
    """Cria campanha + permissões/dashboards padrão + primeiro ADMIN, numa única transação.
    `campaign_data`: campos de Campaign (cleaned_data do CampaignForm); `admin_data`: name, email, phone, password."""
    password, generated = _issue_password(admin_data.get("password", ""))
    for _ in range(3):  # repete se outra criação simultânea tomar o mesmo identificador/código de convite
        try:
            with transaction.atomic():
                campaign = Campaign.objects.create(slug=new_campaign_slug(campaign_data["ballot_name"]), **campaign_data)
                bootstrap_campaign(campaign)
                admin = User.objects.create_user(
                    admin_data["email"],
                    password,
                    must_change_password=True, name=admin_data["name"],
                    phone=admin_data.get("phone", ""),
                    role=Role.ADMIN,
                    campaign=campaign,
                )
                audit(
                    "campaign.create",
                    request=request,
                    campaign=campaign,
                    entity="Campaign",
                    entity_id=campaign.pk,
                    details={"slug": campaign.slug, "ballot_name": campaign.ballot_name, "office": campaign.office},
                )
                audit(
                    "user.create",
                    request=request,
                    campaign=campaign,
                    entity="User",
                    entity_id=admin.pk,
                    details={"role": Role.ADMIN, "password_generated": generated},
                )
            return campaign, admin, _credentials(admin, password, generated)
        except IntegrityError:
            if email_in_use(admin_data["email"]):
                raise EmailAlreadyUsed from None
    raise ServiceError("Não foi possível criar a campanha. Tente novamente.")


def update_campaign(request, form) -> list[str]:
    """Grava o CampaignForm (instance existente) e audita os campos alterados. Devolve os nomes alterados."""
    changed = list(form.changed_data)
    if not changed:
        return []
    with transaction.atomic():
        campaign = form.save()
        audit(
            "campaign.update",
            request=request,
            campaign=campaign,
            entity="Campaign",
            entity_id=campaign.pk,
            details={"fields": changed},
        )
    return changed


def set_campaign_status(request, campaign: Campaign, *, suspend: bool) -> int | None:
    """Suspende ou reativa a campanha (o middleware bloqueia o acesso de quem é da campanha suspensa).
    Devolve None se já estava no status pedido; senão, a quantidade de disparos em andamento que foram pausados."""
    target = CampaignStatus.SUSPENDED if suspend else CampaignStatus.ACTIVE
    if campaign.status == target:
        return None
    paused = 0
    with transaction.atomic():
        campaign.status = target
        campaign.save(update_fields=["status", "updated_at"])
        if suspend:  # campanha suspensa não pode continuar enviando mensagens
            paused = Broadcast.objects.filter(campaign=campaign, status=BroadcastStatus.RUNNING).update(
                status=BroadcastStatus.PAUSED, updated_at=timezone.now()
            )
        audit(
            "campaign.suspend" if suspend else "campaign.activate",
            request=request,
            campaign=campaign,
            entity="Campaign",
            entity_id=campaign.pk,
            details={"slug": campaign.slug, "paused_broadcasts": paused} if suspend else {"slug": campaign.slug},
        )
    return paused


def _delete_voters(campaign_id) -> None:
    """Apaga os eleitores da campanha em lotes (o Django carrega as linhas na memória para tratar as relações)."""
    voters = Voter.objects.filter(campaign_id=campaign_id)
    while True:
        batch = list(voters.order_by().values_list("pk", flat=True)[:VOTER_DELETE_CHUNK])
        if not batch:
            return
        Voter.objects.filter(pk__in=batch).delete()


def delete_campaign(request, campaign: Campaign) -> None:
    """Exclusão definitiva. Voter.registered_by é RESTRICT: os eleitores saem ANTES (equipe e demais dados da
    campanha caem em cascata com a campanha). A auditoria fica sem campanha (a campanha deixa de existir)."""
    campaign_id, slug, ballot_name = campaign.pk, campaign.slug, campaign.ballot_name
    try:
        with transaction.atomic():
            _delete_voters(campaign_id)
            campaign.delete()
            audit(
                "campaign.delete",
                request=request,
                campaign_id=None,
                entity="Campaign",
                entity_id=campaign_id,
                details={"slug": slug, "ballot_name": ballot_name},
            )
    except (RestrictedError, ProtectedError):
        raise ServiceError("Não foi possível excluir: há registros vinculados à campanha. Tente novamente.") from None


# ---------------------------------------------------------------------------------------------
# Contas (administradores de campanha e super admins)
# ---------------------------------------------------------------------------------------------


def create_account(request, *, role: str, campaign: Campaign | None, data: dict) -> tuple[User, IssuedCredentials]:
    """Cria um ADMIN de campanha (campaign informada) ou um SUPER_ADMIN (campaign=None)."""
    password, generated = _issue_password(data.get("password", ""))
    for _ in range(3):
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    data["email"], password, must_change_password=True, name=data["name"], phone=data.get("phone", ""), role=role, campaign=campaign
                )
                audit(
                    "user.create",
                    request=request,
                    campaign=campaign,
                    entity="User",
                    entity_id=user.pk,
                    details={"role": role, "password_generated": generated},
                )
            return user, _credentials(user, password, generated)
        except IntegrityError:
            if email_in_use(data["email"]):
                raise EmailAlreadyUsed from None
    raise ServiceError("Não foi possível criar o usuário. Tente novamente.")


def reset_password(request, user: User, *, campaign: Campaign | None = None) -> IssuedCredentials:
    """Nova senha provisória. Trocar a senha invalida as sessões abertas do usuário (hash de sessão do Django)."""
    password = generate_temp_password()
    with transaction.atomic():
        user.set_password(password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        audit(
            "user.password_reset",
            request=request,
            campaign=campaign,
            entity="User",
            entity_id=user.pk,
            details={"role": user.role},
        )
    return _credentials(user, password, True)


def set_user_active(request, user: User, *, active: bool, campaign: Campaign | None = None) -> bool:
    """Ativa/desativa uma conta. Regras: o super admin não desativa a si mesmo; a plataforma mantém ao menos um
    super admin ativo e cada campanha ao menos um administrador ativo. Devolve False se nada mudou."""
    if user.is_active == active:
        return False
    with transaction.atomic():
        if not active:
            if user.pk == request.user.pk:
                raise ServiceError("Você não pode desativar a sua própria conta.")
            # Trava os pares ativos para que duas desativações simultâneas não zerem os acessos
            peers = list(
                User.objects.select_for_update()
                .filter(role=user.role, campaign_id=user.campaign_id, is_active=True)
                .exclude(pk=user.pk)
                .values_list("pk", flat=True)
            )
            if not peers:
                if user.role == Role.SUPER_ADMIN:
                    raise ServiceError("A plataforma precisa de pelo menos um super admin ativo.")
                raise ServiceError(
                    "A campanha precisa de pelo menos um administrador ativo. "
                    "Para bloquear o acesso de toda a equipe, suspenda a campanha."
                )
        user.is_active = active
        user.save(update_fields=["is_active", "updated_at"])
        audit(
            "user.activate" if active else "user.deactivate",
            request=request,
            campaign=campaign,
            entity="User",
            entity_id=user.pk,
            details={"role": user.role},
        )
    return True
