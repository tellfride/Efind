"""Formulários da equipe. Todo id vindo do cliente (superior, destino de transferência...) é validado contra a
campanha e o escopo do usuário logado; papel/superior são decididos por `rules.resolve_placement`."""

from __future__ import annotations

from django import forms
from django.contrib.auth import password_validation

from apps.accounts.services import email_in_use
from apps.core.access import team_scope
from apps.core.constants import CAMPAIGN_ROLES, Role, label_of
from apps.core.forms import PhoneField, StyledFormMixin

from . import queries
from .rules import (
    new_parent_error_on_delete,
    resolve_placement,
    same_id,
    validate_delete_plan,
    validate_role_change,
)

EMAIL_TAKEN = "Este e-mail já está cadastrado no E-Find. Use outro e-mail."
ROLE_CHOICES = [(r.value, r.label) for r in CAMPAIGN_ROLES]


def _uuid_field(label: str, error: str) -> forms.UUIDField:
    return forms.UUIDField(label=label, required=False, error_messages={"invalid": error})


def validate_member_password(value: str) -> str:
    """Senha informada manualmente pelo admin/coordenador (a provisória gerada não passa por aqui)."""
    if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        raise forms.ValidationError("A senha deve conter letras e números.")
    password_validation.validate_password(value)
    return value


class _MemberBaseForm(StyledFormMixin, forms.Form):
    """Campos comuns de criação e edição."""

    name = forms.CharField(label="Nome completo", min_length=3, max_length=160)
    phone = PhoneField(label="Telefone / WhatsApp", required=False)
    goal = forms.IntegerField(
        label="Meta de cadastros",
        required=False,
        min_value=0,
        max_value=1_000_000,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": "0", "placeholder": "Ex.: 300"}),
        error_messages={"invalid": "Informe um número inteiro.", "min_value": "A meta não pode ser negativa."},
        help_text="Quantidade de eleitores que o membro deve cadastrar. Deixe em branco para não definir meta.",
    )
    region = forms.CharField(
        label="Região de atuação",
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Zona Norte"}),
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.is_admin = actor.role == Role.ADMIN

    # Superiores possíveis (para o Alpine e para a validação)
    def _candidate_payload(self, candidates, exclude_pk=None) -> list[dict]:
        return [
            {
                "id": str(c.pk),
                "name": c.name,
                "role": c.role,
                "active": c.is_active,
                "label": f"{c.name} · {label_of(Role, c.role)}" + ("" if c.is_active else " (inativo)"),
            }
            for c in candidates
            if exclude_pk is None or not same_id(c.pk, exclude_pk)
        ]


class MemberCreateForm(_MemberBaseForm):
    email = forms.EmailField(
        label="E-mail de acesso",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "off", "placeholder": "nome@exemplo.com.br"}),
        error_messages={"invalid": "Informe um e-mail válido."},
    )
    role = forms.ChoiceField(
        label="Papel",
        required=False,
        choices=ROLE_CHOICES,
        error_messages={"invalid_choice": "Escolha um papel válido."},
    )
    parent = _uuid_field("Responsável", "Responsável inválido.")
    password = forms.CharField(
        label="Senha provisória",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Opcional. Se deixar em branco, o sistema gera uma senha provisória e mostra uma única vez.",
    )
    field_order = ["name", "email", "phone", "role", "parent", "goal", "region", "password"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        self.candidates = queries.parent_candidates(actor.campaign_id) if self.is_admin else []
        self.has_active_coordinators = queries.has_active_coordinators(actor.campaign_id)
        self.fields["role"].widget.attrs.update({"x-model": "role", "@change": "onRoleChange()"})
        if not self.is_admin:
            # Coordenador: o superior é sempre ele mesmo (o campo nem existe); o papel é sempre CABO (revalidado)
            del self.fields["parent"]

    @property
    def alpine_config(self) -> dict:
        """Dados para o componente Alpine `memberForm` (apenas conveniência: o servidor revalida tudo)."""
        role = (self["role"].value() or Role.CABO.value) if self.is_admin else Role.CABO.value
        return {
            "role": role,
            "parent": str(self["parent"].value() or "") if "parent" in self.fields else "",
            "originalParent": "",
            "originalRole": "",
            "candidates": self._candidate_payload(self.candidates),
            "hasCoordinators": self.has_active_coordinators,
            "actorId": str(self.actor.pk),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if email_in_use(email):
            raise forms.ValidationError(EMAIL_TAKEN)
        return email

    def clean_password(self):
        value = self.cleaned_data.get("password") or ""
        return validate_member_password(value) if value else ""

    def clean(self):
        data = super().clean()
        if "role" in self.errors or "parent" in self.errors:
            return data
        placement = resolve_placement(
            actor=self.actor,
            requested_role=data.get("role") or (None if self.is_admin else Role.CABO.value),
            requested_parent_id=data.get("parent"),
            candidates=self.candidates,
            has_active_coordinators=self.has_active_coordinators,
        )
        if not placement.ok:
            # Coordenador não vê os campos de papel/superior: o erro vai como erro geral do formulário
            field = placement.field if (self.is_admin and placement.field in self.fields) else None
            self.add_error("parent" if field == "parent" else ("role" if field == "role" else None), placement.error)
        else:
            data["placement"] = placement
        return data


class MemberEditForm(_MemberBaseForm):
    """Edição. Coordenador altera só nome/telefone/meta/região dos seus cabos; ADMIN também e-mail, papel e superior."""

    email = forms.EmailField(
        label="E-mail de acesso",
        max_length=254,
        required=False,
        error_messages={"invalid": "Informe um e-mail válido."},
    )
    role = forms.ChoiceField(
        label="Papel", required=False, choices=ROLE_CHOICES, error_messages={"invalid_choice": "Escolha um papel válido."}
    )
    parent = _uuid_field("Responsável", "Responsável inválido.")
    field_order = ["name", "email", "phone", "role", "parent", "goal", "region"]

    def __init__(self, *args, actor, target, **kwargs):
        kwargs.setdefault(
            "initial",
            {
                "name": target.name,
                "email": target.email,
                "phone": target.phone,
                "role": target.role,
                "parent": target.parent_id,
                "goal": target.goal,
                "region": target.region,
            },
        )
        super().__init__(*args, actor=actor, **kwargs)
        self.target = target
        if not self.is_admin:
            for name in ("email", "role", "parent"):
                del self.fields[name]
            self.candidates = []
            self.has_active_coordinators = False
        else:
            self.candidates = queries.parent_candidates(actor.campaign_id)
            self.has_active_coordinators = queries.has_active_coordinators(actor.campaign_id, exclude_pk=target.pk)
            self.fields["email"].required = True
            self.fields["email"].widget.attrs["required"] = "required"
            self.fields["role"].widget.attrs.update({"x-model": "role", "@change": "onRoleChange()"})

    @property
    def alpine_config(self) -> dict:
        return {
            "role": (self["role"].value() if "role" in self.fields else self.target.role) or self.target.role,
            "parent": str(self["parent"].value() or "") if "parent" in self.fields else "",
            "originalParent": str(self.target.parent_id or ""),
            "originalRole": self.target.role,
            "candidates": self._candidate_payload(self.candidates, exclude_pk=self.target.pk),
            "hasCoordinators": self.has_active_coordinators,
            "actorId": str(self.actor.pk),
        }

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and email_in_use(email, exclude_pk=self.target.pk):
            raise forms.ValidationError(EMAIL_TAKEN)
        return email

    def clean(self):
        data = super().clean()
        if not self.is_admin or "role" in self.errors or "parent" in self.errors:
            return data
        new_role = data.get("role") or self.target.role
        if new_role != self.target.role:
            error = validate_role_change(
                actor=self.actor,
                target=self.target,
                new_role=new_role,
                children_count=queries.children_count(self.actor.campaign_id, self.target.pk),
                other_active_admins=queries.other_active_admins(self.actor.campaign_id, self.target.pk),
            )
            if error:
                self.add_error("role", error)
                return data
        placement = resolve_placement(
            actor=self.actor,
            requested_role=new_role,
            requested_parent_id=data.get("parent"),
            candidates=self.candidates,
            has_active_coordinators=self.has_active_coordinators,
            target=self.target,
        )
        if not placement.ok:
            self.add_error(placement.field if placement.field in self.fields else None, placement.error)
        else:
            data["placement"] = placement
        return data


class MemberDeleteForm(StyledFormMixin, forms.Form):
    """Exclusão: exige destino dos eleitores e novo responsável dos membros vinculados quando existirem."""

    transfer_to = _uuid_field("Transferir os eleitores para", "Membro inválido.")
    new_parent = _uuid_field("Novo responsável pelos membros vinculados", "Responsável inválido.")

    def __init__(self, *args, actor, target, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.target = target
        campaign_id = actor.campaign_id
        self.voters_count = queries.voters_count(campaign_id, target.pk)
        self.children_count = queries.children_count(campaign_id, target.pk)
        self.has_other_active_coordinators = queries.has_active_coordinators(campaign_id, exclude_pk=target.pk)

        # Destino dos eleitores: membros ATIVOS do escopo de quem exclui (exceto o excluído)
        self.transfer_options = list(
            team_scope(actor).filter(is_active=True).exclude(pk=target.pk).order_by("name")
        )
        # Novo responsável: administradores/coordenadores ativos que a regra aceita
        candidates = [c for c in queries.parent_candidates(campaign_id) if not same_id(c.pk, target.pk)]
        self.new_parent_options = [
            c
            for c in candidates
            if c.is_active and new_parent_error_on_delete(target.role, c, self.has_other_active_coordinators) is None
        ]
        self._new_parent_pool = candidates

    @property
    def needs_transfer(self) -> bool:
        return self.voters_count > 0

    @property
    def needs_new_parent(self) -> bool:
        return self.children_count > 0

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        transfer_id, parent_id = data.get("transfer_to"), data.get("new_parent")
        transfer_to = None
        if self.voters_count > 0 and transfer_id:
            transfer_to = next((u for u in self.transfer_options if same_id(u.pk, transfer_id)), None)
            if transfer_to is None:
                # fora do escopo, inativo, de outra campanha ou o próprio excluído
                self.add_error("transfer_to", "Escolha um membro ativo da sua equipe para receber os eleitores.")
                return data
        new_parent = None
        if self.children_count > 0 and parent_id:
            new_parent = next((u for u in self._new_parent_pool if same_id(u.pk, parent_id)), None)
            if new_parent is None:
                self.add_error("new_parent", "Responsável inválido.")
                return data
        plan = validate_delete_plan(
            target=self.target,
            voters_count=self.voters_count,
            children_count=self.children_count,
            transfer_to=transfer_to,
            new_parent=new_parent,
            has_other_active_coordinators=self.has_other_active_coordinators,
        )
        if not plan.ok:
            self.add_error(plan.field if plan.field in self.fields else None, plan.error)
        data["transfer_to_obj"] = transfer_to
        data["new_parent_obj"] = new_parent
        return data


class MoveMemberForm(forms.Form):
    parent = forms.UUIDField(error_messages={"required": "Escolha o novo responsável.", "invalid": "Responsável inválido."})

