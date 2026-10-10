"""Regras puras da equipe (sem banco): posição na hierarquia, quem gerencia quem e travas de segurança.

As views/serviços carregam os dados do banco (sempre limitados à campanha e ao escopo do usuário logado) e
decidem aqui. Os objetos recebidos precisam apenas de `id`, `role`, `parent_id` e/ou `is_active`
(models `User` ou qualquer objeto simples), então tudo é testável sem banco.

Hierarquia:  ADMIN → COORDENADOR (superior = admin) → CABO (superior = coordenador; admin se não há coordenadores).
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from apps.core.constants import CAMPAIGN_ROLES, Role, label_of

# --------------------------------------------------------------------------------------------
# Tipos auxiliares
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """Resultado de `resolve_placement`: papel e superior definidos, ou um erro (com o campo afetado)."""

    ok: bool
    role: str | None = None
    parent_id: Any = None
    error: str = ""
    field: str | None = None  # "role" | "parent" | None (erro geral)


@dataclass(frozen=True)
class PlanResult:
    ok: bool
    error: str = ""
    field: str | None = None  # "transfer_to" | "new_parent" | None


def same_id(a: Any, b: Any) -> bool:
    """Compara ids (UUID ou str) sem confundir None com None."""
    return a is not None and b is not None and str(a) == str(b)


def is_campaign_role(value: Any) -> bool:
    return isinstance(value, str) and value in CAMPAIGN_ROLES


def _fail(error: str, field: str | None = None) -> Placement:
    return Placement(ok=False, error=error, field=field)


# --------------------------------------------------------------------------------------------
# Papel e superior
# --------------------------------------------------------------------------------------------


def default_parent_id(actor: Any, role: str, has_active_coordinators: bool) -> Any:
    """Superior sugerido quando o formulário não informa:
    - coordenador cadastrando → ele mesmo;
    - admin cadastrando coordenador → o próprio admin;
    - admin cadastrando cabo → o próprio admin apenas se não houver coordenadores ativos."""
    if role == Role.ADMIN:
        return None
    if actor.role == Role.COORDENADOR:
        return actor.id
    if role == Role.COORDENADOR:
        return actor.id
    return None if has_active_coordinators else actor.id


def resolve_placement(
    *,
    actor: Any,
    requested_role: str | None = None,
    requested_parent_id: Any = None,
    candidates: Iterable[Any] = (),
    has_active_coordinators: bool = False,
    target: Any = None,
) -> Placement:
    """Define papel e superior de um membro novo (ou editado, quando `target` é informado).

    - CABO não cadastra ninguém.
    - COORDENADOR só cadastra/edita CABO da própria equipe; o superior é sempre ele mesmo (o enviado é ignorado)
      e pedir outro papel é recusado.
    - ADMIN: ADMIN não tem superior; COORDENADOR fica abaixo de um ADMIN ativo; CABO abaixo de um COORDENADOR
      ativo — ou de um ADMIN quando a campanha não tem coordenadores ativos.
    - Na edição, manter o mesmo superior (e o mesmo papel) é sempre aceito, mesmo que ele esteja inativo.

    `candidates` deve conter somente usuários DA CAMPANHA do ator (com `id`, `role`, `is_active`).
    """
    if actor.role == Role.CABO:
        return _fail("Cabos eleitorais não podem cadastrar nem reposicionar membros da equipe.")

    if actor.role == Role.COORDENADOR:
        if requested_role and requested_role != Role.CABO:
            return _fail("Coordenadores só podem cadastrar cabos eleitorais.", "role")
        if target is not None and (target.role != Role.CABO or not same_id(target.parent_id, actor.id)):
            return _fail("Você só pode gerenciar os cabos eleitorais da sua equipe.")
        return Placement(ok=True, role=Role.CABO.value, parent_id=actor.id)

    if actor.role != Role.ADMIN:
        return _fail("Você não pode gerenciar a equipe.")

    role = requested_role or (target.role if target is not None else None)
    if not is_campaign_role(role):
        return _fail("Escolha um papel válido.", "role")
    role = str(role)
    if role == Role.ADMIN:
        return Placement(ok=True, role=role, parent_id=None)

    parent_id = (
        requested_parent_id
        or (target.parent_id if target is not None and target.role == role else None)
        or default_parent_id(actor, role, has_active_coordinators)
    )
    if not parent_id:
        return _fail(
            "Escolha o coordenador responsável." if role == Role.CABO else "Escolha o administrador responsável.",
            "parent",
        )
    if target is not None and same_id(parent_id, target.id):
        return _fail("Um membro não pode ser o próprio responsável.", "parent")

    parent = next((c for c in candidates if same_id(c.id, parent_id)), None)
    if parent is None:
        return _fail("Responsável inválido.", "parent")

    unchanged = target is not None and same_id(target.parent_id, parent_id) and target.role == role
    if not parent.is_active and not unchanged:
        return _fail("O responsável escolhido está inativo.", "parent")

    if role == Role.COORDENADOR:
        if parent.role != Role.ADMIN:
            return _fail("O coordenador deve ficar abaixo de um administrador.", "parent")
        return Placement(ok=True, role=role, parent_id=parent.id)

    # CABO
    if parent.role == Role.COORDENADOR:
        return Placement(ok=True, role=role, parent_id=parent.id)
    if parent.role == Role.ADMIN:
        if has_active_coordinators and not unchanged:
            return _fail(
                "Escolha um coordenador: o cabo só fica abaixo do administrador quando não há coordenadores ativos.",
                "parent",
            )
        return Placement(ok=True, role=role, parent_id=parent.id)
    return _fail("O cabo eleitoral deve ficar abaixo de um coordenador.", "parent")


def parent_options_for(role: str, candidates: Iterable[Any], has_active_coordinators: bool) -> list[Any]:
    """Superiores ATIVOS que o ADMIN pode escolher para um membro do papel informado (mesma regra do formulário)."""
    active = [c for c in candidates if c.is_active]
    if role == Role.COORDENADOR:
        return [c for c in active if c.role == Role.ADMIN]
    if role == Role.CABO:
        coordinators = [c for c in active if c.role == Role.COORDENADOR]
        if coordinators or has_active_coordinators:
            return coordinators
        return [c for c in active if c.role == Role.ADMIN]
    return []


# --------------------------------------------------------------------------------------------
# Quem gerencia quem
# --------------------------------------------------------------------------------------------


def can_manage_member(actor: Any, target: Any) -> bool:
    """ADMIN: qualquer membro da campanha. COORDENADOR: apenas os seus cabos. CABO: ninguém.
    O chamador garante que o alvo é da mesma campanha (carregado com `team_scope`)."""
    if actor.role == Role.ADMIN:
        return True
    if actor.role == Role.COORDENADOR:
        return (
            not same_id(target.id, actor.id) and target.role == Role.CABO and same_id(target.parent_id, actor.id)
        )
    return False


OPERATION_DEACTIVATE = "deactivate"
OPERATION_DELETE = "delete"
OPERATION_RESET_PASSWORD = "reset_password"


def check_self_and_last_admin(
    operation: str, actor_id: Any, target: Any, other_active_admins: int
) -> str | None:
    """Travas comuns: ninguém desativa/exclui/redefine a senha de si mesmo por aqui, e a campanha nunca fica sem
    administrador ativo. `other_active_admins` = administradores ativos da campanha, exceto o alvo."""
    if same_id(target.id, actor_id):
        if operation == OPERATION_DEACTIVATE:
            return "Você não pode desativar o seu próprio acesso."
        if operation == OPERATION_DELETE:
            return "Você não pode excluir o seu próprio usuário."
        return "Para trocar a sua senha, use a página Meu perfil."
    if target.role == Role.ADMIN and other_active_admins == 0:
        if operation == OPERATION_DEACTIVATE and target.is_active:
            return "Não é possível desativar o último administrador ativo da campanha."
        if operation == OPERATION_DELETE:
            return "Não é possível excluir o último administrador da campanha."
    return None


def validate_role_change(
    *, actor: Any, target: Any, new_role: str, children_count: int, other_active_admins: int
) -> str | None:
    """Mudança de papel (somente ADMIN): nunca o próprio papel, nunca deixar a campanha sem administrador ativo
    e só para quem não tem membros vinculados (ex.: coordenador → cabo exige que ele não tenha cabos)."""
    if new_role == target.role:
        return None
    if actor.role != Role.ADMIN:
        return "Apenas administradores podem alterar o papel de um membro."
    if not is_campaign_role(new_role):
        return "Papel inválido."
    if same_id(target.id, actor.id):
        return "Você não pode alterar o seu próprio papel."
    if target.role == Role.ADMIN and target.is_active and other_active_admins == 0:
        return "Não é possível alterar o papel do último administrador ativo da campanha."
    if children_count > 0:
        noun = "membro vinculado" if children_count == 1 else "membros vinculados"
        return (
            f"Este membro tem {children_count} {noun}. "
            "Mova-os para outro responsável antes de alterar o papel."
        )
    return None


# --------------------------------------------------------------------------------------------
# Exclusão
# --------------------------------------------------------------------------------------------


def new_parent_error_on_delete(target_role: str, parent: Any, has_other_active_coordinators: bool) -> str | None:
    """O `parent` pode assumir os membros vinculados de um membro excluído (papel `target_role`)?"""
    if not parent.is_active:
        return "O novo responsável está inativo."
    if target_role == Role.ADMIN:
        if parent.role != Role.ADMIN:
            return "Os membros vinculados a um administrador devem passar para outro administrador."
    elif parent.role == Role.ADMIN:
        if has_other_active_coordinators:
            return "Escolha um coordenador ativo para receber os cabos eleitorais."
    elif parent.role != Role.COORDENADOR:
        return "Os cabos eleitorais devem passar para um coordenador."
    return None


def validate_delete_plan(
    *,
    target: Any,
    voters_count: int,
    children_count: int,
    transfer_to: Any,
    new_parent: Any,
    has_other_active_coordinators: bool,
) -> PlanResult:
    """Exclusão de membro: se ele tem eleitores, é obrigatório transferi-los para outro membro ativo do escopo;
    se tem membros vinculados, é obrigatório escolher o novo responsável deles.
    `transfer_to` deve ter sido carregado dentro do escopo do ator; `new_parent`, dentro da campanha."""
    if voters_count > 0:
        if transfer_to is None:
            return PlanResult(
                False, "Escolha para quem transferir os eleitores cadastrados por este membro.", "transfer_to"
            )
        if same_id(transfer_to.id, target.id):
            return PlanResult(False, "Escolha outro membro para receber os eleitores.", "transfer_to")
        if not transfer_to.is_active:
            return PlanResult(False, "O membro que vai receber os eleitores está inativo.", "transfer_to")
    if children_count > 0:
        if new_parent is None:
            return PlanResult(False, "Escolha o novo responsável pelos membros vinculados.", "new_parent")
        if same_id(new_parent.id, target.id):
            return PlanResult(False, "Escolha outro responsável.", "new_parent")
        error = new_parent_error_on_delete(target.role, new_parent, has_other_active_coordinators)
        if error:
            return PlanResult(False, error, "new_parent")
    return PlanResult(True)


# --------------------------------------------------------------------------------------------
# Metas, senha provisória e mensagem de acesso
# --------------------------------------------------------------------------------------------


def goal_percent(total: int, goal: int | None) -> float | None:
    """Percentual da meta (None quando não há meta definida)."""
    if not goal or goal <= 0:
        return None
    return total / goal * 100


def goal_tone(percent: float | None) -> str:
    """Cor da barra de progresso da meta."""
    if percent is None:
        return "brand"
    if percent >= 100:
        return "green"
    if percent >= 50:
        return "brand"
    if percent >= 25:
        return "yellow"
    return "red"


_PASSWORD_LETTERS = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"  # sem caracteres ambíguos (i, l, o, I, O)
_PASSWORD_DIGITS = "23456789"


def generate_temp_password() -> str:
    """Senha provisória legível (8 letras + 2 dígitos), gerada com `secrets`."""
    letters = "".join(secrets.choice(_PASSWORD_LETTERS) for _ in range(8))
    digits = "".join(secrets.choice(_PASSWORD_DIGITS) for _ in range(2))
    return letters + digits


def build_access_message(
    *,
    member_name: str,
    campaign_name: str,
    role: str,
    login_url: str,
    email: str,
    password: str,
    registration_url: str | None = None,
    reset: bool = False,
) -> str:
    """Mensagem com os dados de acesso para enviar ao membro (WhatsApp ou copiar)."""
    parts = (member_name or "").strip().split()
    first = parts[0] if parts else member_name
    if reset:
        intro = f"Olá, {first}! Sua senha de acesso ao E-Find (campanha {campaign_name}) foi redefinida."
    else:
        intro = (
            f"Olá, {first}! Você foi cadastrado(a) como {label_of(Role, role).lower()} "
            f"na equipe da campanha {campaign_name} no E-Find."
        )
    lines = [intro, "", f"Acesse: {login_url}", f"E-mail: {email}", f"Senha provisória: {password}"]
    if registration_url:
        lines += ["", f"Seu link para cadastrar eleitores: {registration_url}"]
    lines += ["", "Por segurança, troque a senha no primeiro acesso (menu Meu perfil)."]
    return "\n".join(lines)
