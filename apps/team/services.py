"""Operações de escrita da equipe (todas atômicas e auditadas). As views validam permissão e escopo antes de chamar;
aqui ficam as travas de negócio (último admin, próprio usuário...) e a gravação. Falhas esperadas levantam
`TeamError` (mensagem em pt-BR para o usuário, com o campo afetado quando houver).

Auditoria: `details` só leva ids, papéis, nomes de campos e contagens — nunca nome, e-mail ou telefone.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from apps.accounts.models import User, UserPermission
from apps.auditlog.service import audit
from apps.core.constants import Role
from apps.voters.models import Voter

from . import queries
from .rules import (
    OPERATION_DEACTIVATE,
    OPERATION_DELETE,
    OPERATION_RESET_PASSWORD,
    Placement,
    check_self_and_last_admin,
    generate_temp_password,
    resolve_placement,
    same_id,
)

EMAIL_TAKEN = "Este e-mail já está cadastrado no E-Find. Use outro e-mail."


class TeamError(Exception):
    """Erro de negócio esperado (exibido ao usuário)."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


def _lock_active_admins(campaign_id) -> None:
    """Trava (SELECT ... FOR UPDATE) os admins ativos da campanha durante a transação, para que duas operações
    simultâneas não removam juntas o último administrador. No SQLite (testes) é ignorado."""
    list(User.objects.select_for_update().filter(campaign_id=campaign_id, role=Role.ADMIN, is_active=True).values_list("pk", flat=True))


# --------------------------------------------------------------------------------------------
# Criar
# --------------------------------------------------------------------------------------------


def create_member(request, data: dict[str, Any]) -> tuple[User, str]:
    """Cria o membro. `data` = cleaned_data de `MemberCreateForm` (inclui "placement"). Devolve (membro, senha em
    claro) — a senha só existe nesta resposta e nunca é gravada em texto."""
    actor = request.user
    placement: Placement = data["placement"]
    password = data.get("password") or generate_temp_password()
    try:
        with transaction.atomic():
            member = User.objects.create_user(
                data["email"],
                password,
                campaign_id=actor.campaign_id,
                must_change_password=True, name=data["name"].strip(),
                phone=data.get("phone") or "",
                role=placement.role,
                parent_id=placement.parent_id,
                goal=data.get("goal"),
                region=(data.get("region") or "").strip(),
            )
    except IntegrityError as exc:
        if User.objects.filter(email__iexact=data["email"]).exists():
            raise TeamError(EMAIL_TAKEN, "email") from exc
        raise TeamError("Não foi possível cadastrar o membro agora. Tente novamente.") from exc
    audit(
        "user.create",
        request=request,
        entity="User",
        entity_id=member.pk,
        details={"role": member.role, "parent_id": str(member.parent_id) if member.parent_id else None, "goal": member.goal},
    )
    return member, password


# --------------------------------------------------------------------------------------------
# Editar / mover
# --------------------------------------------------------------------------------------------


def update_member(request, target: User, data: dict[str, Any]) -> list[str]:
    """Aplica a edição. `data` = cleaned_data de `MemberEditForm` (ADMIN inclui email e "placement").
    Devolve os nomes dos campos alterados."""
    actor = request.user
    changed: list[str] = []

    def assign(field: str, value: Any) -> None:
        if getattr(target, field) != value:
            setattr(target, field, value)
            changed.append(field)

    old_role, old_parent = target.role, target.parent_id
    assign("name", data["name"].strip())
    assign("phone", data.get("phone") or "")
    assign("goal", data.get("goal"))
    assign("region", (data.get("region") or "").strip())

    if actor.role == Role.ADMIN:
        if data.get("email"):
            assign("email", data["email"].strip().lower())
        placement: Placement | None = data.get("placement")
        if placement is not None:
            assign("role", placement.role)
            assign("parent_id", placement.parent_id)

    role_changed = target.role != old_role
    if not changed:
        return []
    try:
        with transaction.atomic():
            if target.role != old_role and old_role == Role.ADMIN:
                _lock_active_admins(actor.campaign_id)
                if queries.other_active_admins(actor.campaign_id, target.pk) == 0 and target.is_active:
                    raise TeamError("Não é possível alterar o papel do último administrador ativo da campanha.", "role")
            target.save(update_fields=[*[f for f in changed], "updated_at"])
            if role_changed:
                # Exceções de permissão valem para o papel anterior: são descartadas ao trocar o papel
                UserPermission.objects.filter(user=target).delete()
    except IntegrityError as exc:
        if "email" in changed:
            raise TeamError(EMAIL_TAKEN, "email") from exc
        raise

    details: dict[str, Any] = {"fields": [f.removesuffix("_id") for f in changed]}
    if role_changed:
        details.update(role_from=old_role, role_to=target.role)
    if not same_id(old_parent, target.parent_id):
        details.update(
            parent_from=str(old_parent) if old_parent else None,
            parent_to=str(target.parent_id) if target.parent_id else None,
        )
    audit("user.update", request=request, entity="User", entity_id=target.pk, details=details)
    return changed


def move_member(request, target: User, parent_id) -> bool:
    """ADMIN move um coordenador/cabo para outro responsável. Devolve False se já estava com ele."""
    actor = request.user
    if actor.role != Role.ADMIN:
        raise TeamError("Apenas administradores podem mover membros entre responsáveis.")
    if target.role == Role.ADMIN:
        raise TeamError("Administradores não ficam abaixo de outro membro.")
    candidates = queries.parent_candidates(actor.campaign_id)
    placement = resolve_placement(
        actor=actor,
        requested_role=target.role,
        requested_parent_id=parent_id,
        candidates=candidates,
        has_active_coordinators=queries.has_active_coordinators(actor.campaign_id, exclude_pk=target.pk),
        target=target,
    )
    if not placement.ok:
        raise TeamError(placement.error, placement.field)
    if same_id(placement.parent_id, target.parent_id):
        return False
    old_parent = target.parent_id
    target.parent_id = placement.parent_id
    target.save(update_fields=["parent", "updated_at"])
    audit(
        "user.update",
        request=request,
        entity="User",
        entity_id=target.pk,
        details={"fields": ["parent"], "moved": True, "parent_from": str(old_parent) if old_parent else None, "parent_to": str(placement.parent_id)},
    )
    return True


# --------------------------------------------------------------------------------------------
# Ativar / desativar
# --------------------------------------------------------------------------------------------


def set_member_active(request, target: User, active: bool) -> bool:
    """Ativa/desativa o acesso. Devolve False quando nada mudou. Desativar nunca vale para si mesmo nem para o
    último administrador ativo. Usuário inativo não consegue entrar e seu link público deixa de funcionar."""
    actor = request.user
    with transaction.atomic():
        if not active:
            _lock_active_admins(actor.campaign_id)
            others = queries.other_active_admins(actor.campaign_id, target.pk) if target.role == Role.ADMIN else 1
            error = check_self_and_last_admin(OPERATION_DEACTIVATE, actor.pk, target, others)
            if error:
                raise TeamError(error)
        if target.is_active == active:
            return False
        target.is_active = active
        target.save(update_fields=["is_active", "updated_at"])
    audit(
        "user.activate" if active else "user.deactivate",
        request=request,
        entity="User",
        entity_id=target.pk,
        details={"role": target.role},
    )
    return True


# --------------------------------------------------------------------------------------------
# Senha e link de cadastro
# --------------------------------------------------------------------------------------------


def reset_member_password(request, target: User) -> str:
    """Gera uma senha provisória (devolvida uma única vez). O Django invalida as outras sessões do membro
    automaticamente porque o hash da sessão muda com a senha."""
    actor = request.user
    error = check_self_and_last_admin(OPERATION_RESET_PASSWORD, actor.pk, target, 1)
    if error:
        raise TeamError(error)
    password = generate_temp_password()
    target.set_password(password)
    target.must_change_password = True
    target.save(update_fields=["password", "must_change_password", "updated_at"])
    audit("user.password_reset", request=request, entity="User", entity_id=target.pk)
    return password


def regenerate_invite(request, target: User) -> str:
    """Novo código de convite: o link e o QR Code anteriores deixam de funcionar."""
    for _ in range(3):
        code = User.objects.unique_invite_code()
        try:
            with transaction.atomic():
                target.invite_code = code
                target.save(update_fields=["invite_code", "updated_at"])
        except IntegrityError:
            continue
        audit(
            "user.invite_regenerate",
            request=request,
            entity="User",
            entity_id=target.pk,
            details={"self": same_id(request.user.pk, target.pk)},
        )
        return code
    raise TeamError("Não foi possível gerar um novo link agora. Tente novamente.")


# --------------------------------------------------------------------------------------------
# Excluir
# --------------------------------------------------------------------------------------------


def delete_member(request, target: User, data: dict[str, Any]) -> dict[str, Any]:
    """Exclui o membro. `data` = cleaned_data de `MemberDeleteForm`: os eleitores dele vão para `transfer_to_obj` e
    os membros vinculados para `new_parent_obj`, tudo na mesma transação. Devolve as contagens para a mensagem."""
    actor = request.user
    campaign_id = actor.campaign_id
    transfer_to, new_parent = data.get("transfer_to_obj"), data.get("new_parent_obj")
    voters_transferred = children_moved = 0
    try:
        with transaction.atomic():
            _lock_active_admins(campaign_id)
            others = queries.other_active_admins(campaign_id, target.pk) if target.role == Role.ADMIN else 1
            error = check_self_and_last_admin(OPERATION_DELETE, actor.pk, target, others)
            if error:
                raise TeamError(error)
            if transfer_to is not None:
                voters_transferred = Voter.objects.filter(campaign_id=campaign_id, registered_by_id=target.pk).update(
                    registered_by_id=transfer_to.pk, updated_at=timezone.now()
                )
            if Voter.objects.filter(registered_by_id=target.pk).exists():
                raise TeamError(
                    "Este membro cadastrou eleitores agora há pouco. Escolha para quem transferi-los e tente novamente.",
                    "transfer_to",
                )
            if new_parent is not None:
                children_moved = User.objects.filter(campaign_id=campaign_id, parent_id=target.pk).update(
                    parent_id=new_parent.pk, updated_at=timezone.now()
                )
            if User.objects.filter(parent_id=target.pk).exists():
                raise TeamError(
                    "Há membros vinculados a este usuário. Escolha o novo responsável e tente novamente.", "new_parent"
                )
            target_pk, target_role = target.pk, target.role
            target.delete()
    except (ProtectedError, RestrictedError) as exc:
        raise TeamError("Não foi possível excluir: ainda há dados vinculados a este membro.") from exc
    audit(
        "user.delete",
        request=request,
        entity="User",
        entity_id=target_pk,
        details={
            "role": target_role,
            "voters_transferred": voters_transferred,
            "transfer_to_id": str(transfer_to.pk) if transfer_to is not None else None,
            "children_moved": children_moved,
            "new_parent_id": str(new_parent.pk) if new_parent is not None else None,
        },
    )
    return {"voters_transferred": voters_transferred, "children_moved": children_moved}
