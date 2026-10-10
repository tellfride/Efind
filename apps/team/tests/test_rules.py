"""Regras puras da equipe (sem banco): papel/superior, quem gerencia quem, travas e exclusão."""

import uuid
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.core.constants import Role
from apps.team import rules
from apps.team.rules import (
    OPERATION_DEACTIVATE,
    OPERATION_DELETE,
    OPERATION_RESET_PASSWORD,
    build_access_message,
    can_manage_member,
    check_self_and_last_admin,
    default_parent_id,
    generate_temp_password,
    goal_percent,
    goal_tone,
    new_parent_error_on_delete,
    parent_options_for,
    resolve_placement,
    validate_delete_plan,
    validate_role_change,
)


def person(role, *, parent_id=None, is_active=True, pk=None):
    pk = pk or uuid.uuid4()
    return SimpleNamespace(id=pk, pk=pk, role=role, parent_id=parent_id, is_active=is_active)


class PlacementMatrixTests(SimpleTestCase):
    """Matriz (ator, papel pedido, superior) → permitido / erro."""

    def setUp(self):
        self.admin = person(Role.ADMIN)
        self.admin2 = person(Role.ADMIN)
        self.coord = person(Role.COORDENADOR, parent_id=self.admin.id)
        self.coord2 = person(Role.COORDENADOR, parent_id=self.admin.id)
        self.coord_off = person(Role.COORDENADOR, parent_id=self.admin.id, is_active=False)
        self.cabo = person(Role.CABO, parent_id=self.coord.id)
        self.candidates = [self.admin, self.admin2, self.coord, self.coord2, self.coord_off]

    def place(self, actor, role=None, parent=None, coordinators=True, **kw):
        return resolve_placement(
            actor=actor,
            requested_role=role,
            requested_parent_id=parent.id if parent is not None else None,
            candidates=kw.pop("candidates", self.candidates),
            has_active_coordinators=coordinators,
            **kw,
        )

    # --- cabo nunca cadastra
    def test_cabo_cannot_place_anyone(self):
        for role in (Role.CABO, Role.COORDENADOR, Role.ADMIN):
            self.assertFalse(self.place(self.cabo, role).ok)

    # --- coordenador
    def test_coordinator_creates_only_cabo_below_himself(self):
        p = self.place(self.coord, Role.CABO)
        self.assertTrue(p.ok)
        self.assertEqual((p.role, p.parent_id), (Role.CABO, self.coord.id))

    def test_coordinator_default_role_is_cabo(self):
        p = self.place(self.coord, None)
        self.assertTrue(p.ok)
        self.assertEqual(p.role, Role.CABO)

    def test_coordinator_forged_parent_is_ignored(self):
        p = self.place(self.coord, Role.CABO, parent=self.coord2)
        self.assertTrue(p.ok)
        self.assertEqual(p.parent_id, self.coord.id)

    def test_coordinator_cannot_request_coordinator_or_admin(self):
        for role in (Role.COORDENADOR, Role.ADMIN):
            p = self.place(self.coord, role)
            self.assertFalse(p.ok, role)
            self.assertEqual(p.field, "role")

    def test_coordinator_cannot_touch_cabo_of_another_coordinator(self):
        other = person(Role.CABO, parent_id=self.coord2.id)
        self.assertFalse(self.place(self.coord, Role.CABO, target=other).ok)
        self.assertFalse(self.place(self.coord, Role.CABO, target=self.coord2).ok)
        mine = person(Role.CABO, parent_id=self.coord.id)
        self.assertTrue(self.place(self.coord, Role.CABO, target=mine).ok)

    # --- admin
    def test_admin_creates_admin_without_parent(self):
        p = self.place(self.admin, Role.ADMIN, parent=self.coord)
        self.assertTrue(p.ok)
        self.assertIsNone(p.parent_id)

    def test_admin_creates_coordinator_below_admin_default_self(self):
        p = self.place(self.admin, Role.COORDENADOR)
        self.assertTrue(p.ok)
        self.assertEqual(p.parent_id, self.admin.id)
        self.assertEqual(self.place(self.admin, Role.COORDENADOR, parent=self.admin2).parent_id, self.admin2.id)

    def test_coordinator_must_be_below_an_admin(self):
        p = self.place(self.admin, Role.COORDENADOR, parent=self.coord)
        self.assertFalse(p.ok)
        self.assertEqual(p.field, "parent")

    def test_cabo_requires_parent_when_coordinators_exist(self):
        p = self.place(self.admin, Role.CABO)
        self.assertFalse(p.ok)
        self.assertEqual(p.field, "parent")

    def test_cabo_below_active_coordinator(self):
        p = self.place(self.admin, Role.CABO, parent=self.coord)
        self.assertTrue(p.ok)
        self.assertEqual(p.parent_id, self.coord.id)

    def test_cabo_below_admin_only_without_active_coordinators(self):
        self.assertFalse(self.place(self.admin, Role.CABO, parent=self.admin).ok)
        p = self.place(self.admin, Role.CABO, parent=self.admin, coordinators=False)
        self.assertTrue(p.ok)
        self.assertEqual(p.parent_id, self.admin.id)
        # sem coordenadores, o superior padrão é o próprio admin
        self.assertEqual(self.place(self.admin, Role.CABO, coordinators=False).parent_id, self.admin.id)

    def test_inactive_or_unknown_parent_is_rejected(self):
        self.assertFalse(self.place(self.admin, Role.CABO, parent=self.coord_off).ok)
        stranger = person(Role.COORDENADOR)  # de outra campanha: não está nos candidatos
        self.assertFalse(self.place(self.admin, Role.CABO, parent=stranger).ok)

    def test_cabo_cannot_be_parent(self):
        self.assertFalse(self.place(self.admin, Role.CABO, parent=self.cabo, candidates=[*self.candidates, self.cabo]).ok)

    def test_invalid_role_is_rejected(self):
        for role in ("SUPER_ADMIN", "DONO", "", None):
            p = self.place(self.admin, role)
            self.assertFalse(p.ok, role)
            self.assertEqual(p.field, "role")

    def test_editing_keeps_inactive_parent_if_unchanged(self):
        cabo = person(Role.CABO, parent_id=self.coord_off.id)
        p = self.place(self.admin, Role.CABO, parent=self.coord_off, target=cabo)
        self.assertTrue(p.ok)
        # mas não pode ESCOLHER um inativo
        other = person(Role.CABO, parent_id=self.coord.id)
        self.assertFalse(self.place(self.admin, Role.CABO, parent=self.coord_off, target=other).ok)

    def test_member_cannot_be_own_parent(self):
        p = self.place(self.admin, Role.COORDENADOR, parent=self.coord, target=self.coord)
        self.assertFalse(p.ok)

    def test_parent_options(self):
        self.assertEqual(parent_options_for(Role.COORDENADOR, self.candidates, True), [self.admin, self.admin2])
        self.assertEqual(parent_options_for(Role.CABO, self.candidates, True), [self.coord, self.coord2])
        self.assertEqual(parent_options_for(Role.CABO, [self.admin, self.coord_off], False), [self.admin])
        self.assertEqual(parent_options_for(Role.ADMIN, self.candidates, True), [])

    def test_default_parent(self):
        self.assertIsNone(default_parent_id(self.admin, Role.ADMIN, True))
        self.assertEqual(default_parent_id(self.coord, Role.CABO, True), self.coord.id)
        self.assertEqual(default_parent_id(self.admin, Role.COORDENADOR, True), self.admin.id)
        self.assertIsNone(default_parent_id(self.admin, Role.CABO, True))
        self.assertEqual(default_parent_id(self.admin, Role.CABO, False), self.admin.id)


class ManageAndGuardTests(SimpleTestCase):
    def setUp(self):
        self.admin = person(Role.ADMIN)
        self.coord = person(Role.COORDENADOR, parent_id=self.admin.id)
        self.other_coord = person(Role.COORDENADOR, parent_id=self.admin.id)
        self.cabo = person(Role.CABO, parent_id=self.coord.id)
        self.other_cabo = person(Role.CABO, parent_id=self.other_coord.id)

    def test_who_manages_whom(self):
        self.assertTrue(can_manage_member(self.admin, self.cabo))
        self.assertTrue(can_manage_member(self.admin, self.coord))
        self.assertTrue(can_manage_member(self.coord, self.cabo))
        self.assertFalse(can_manage_member(self.coord, self.other_cabo))
        self.assertFalse(can_manage_member(self.coord, self.other_coord))
        self.assertFalse(can_manage_member(self.coord, self.coord))
        self.assertFalse(can_manage_member(self.coord, self.admin))
        self.assertFalse(can_manage_member(self.cabo, self.cabo))

    def test_self_protection(self):
        for op in (OPERATION_DEACTIVATE, OPERATION_DELETE, OPERATION_RESET_PASSWORD):
            self.assertTrue(check_self_and_last_admin(op, self.admin.id, self.admin, 5), op)
        self.assertIsNone(check_self_and_last_admin(OPERATION_DEACTIVATE, self.admin.id, self.cabo, 1))

    def test_last_admin_protection(self):
        other = person(Role.ADMIN)
        self.assertIn("último administrador", check_self_and_last_admin(OPERATION_DEACTIVATE, self.admin.id, other, 0))
        self.assertIn("último administrador", check_self_and_last_admin(OPERATION_DELETE, self.admin.id, other, 0))
        self.assertIsNone(check_self_and_last_admin(OPERATION_DEACTIVATE, self.admin.id, other, 1))
        # já inativo: desativar de novo não é bloqueado
        other.is_active = False
        self.assertIsNone(check_self_and_last_admin(OPERATION_DEACTIVATE, self.admin.id, other, 0))
        # redefinir a senha do único admin (por outro) não é bloqueado
        self.assertIsNone(check_self_and_last_admin(OPERATION_RESET_PASSWORD, self.admin.id, person(Role.ADMIN), 0))

    def test_role_change_rules(self):
        kw = {"actor": self.admin, "children_count": 0, "other_active_admins": 1}
        self.assertIsNone(validate_role_change(target=self.cabo, new_role=Role.CABO, **kw))  # igual
        self.assertIsNone(validate_role_change(target=self.cabo, new_role=Role.COORDENADOR, **kw))
        self.assertIsNone(validate_role_change(target=self.coord, new_role=Role.CABO, **kw))
        # coordenador → cabo só sem membros vinculados
        err = validate_role_change(target=self.coord, new_role=Role.CABO, **{**kw, "children_count": 2})
        self.assertIn("2 membros vinculados", err)
        # nunca o próprio papel
        self.assertTrue(validate_role_change(target=self.admin, new_role=Role.CABO, **kw))
        # nunca o último admin
        other = person(Role.ADMIN)
        self.assertTrue(validate_role_change(target=other, new_role=Role.CABO, **{**kw, "other_active_admins": 0}))
        # coordenador não altera papéis
        self.assertTrue(validate_role_change(actor=self.coord, target=self.cabo, new_role=Role.COORDENADOR, children_count=0, other_active_admins=1))
        # papel inválido
        self.assertTrue(validate_role_change(target=self.cabo, new_role="SUPER_ADMIN", **kw))


class DeletePlanTests(SimpleTestCase):
    def setUp(self):
        self.admin = person(Role.ADMIN)
        self.coord = person(Role.COORDENADOR, parent_id=self.admin.id)
        self.coord2 = person(Role.COORDENADOR, parent_id=self.admin.id)
        self.cabo = person(Role.CABO, parent_id=self.coord.id)
        self.cabo2 = person(Role.CABO, parent_id=self.coord.id)

    def plan(self, target, voters=0, children=0, transfer=None, new_parent=None, others=True):
        return validate_delete_plan(
            target=target,
            voters_count=voters,
            children_count=children,
            transfer_to=transfer,
            new_parent=new_parent,
            has_other_active_coordinators=others,
        )

    def test_without_dependencies_no_choice_needed(self):
        self.assertTrue(self.plan(self.cabo).ok)

    def test_voters_require_active_other_member(self):
        r = self.plan(self.cabo, voters=3)
        self.assertFalse(r.ok)
        self.assertEqual(r.field, "transfer_to")
        self.assertFalse(self.plan(self.cabo, voters=3, transfer=self.cabo).ok)
        inactive = person(Role.CABO, is_active=False)
        self.assertFalse(self.plan(self.cabo, voters=3, transfer=inactive).ok)
        self.assertTrue(self.plan(self.cabo, voters=3, transfer=self.cabo2).ok)

    def test_children_require_new_parent(self):
        r = self.plan(self.coord, children=2)
        self.assertEqual((r.ok, r.field), (False, "new_parent"))
        self.assertFalse(self.plan(self.coord, children=2, new_parent=self.coord).ok)
        self.assertTrue(self.plan(self.coord, children=2, new_parent=self.coord2).ok)

    def test_new_parent_rules(self):
        inactive = person(Role.COORDENADOR, is_active=False)
        self.assertTrue(new_parent_error_on_delete(Role.COORDENADOR, inactive, True))
        # cabos do coordenador excluído: admin só se não há outro coordenador ativo
        self.assertTrue(new_parent_error_on_delete(Role.COORDENADOR, self.admin, True))
        self.assertIsNone(new_parent_error_on_delete(Role.COORDENADOR, self.admin, False))
        self.assertIsNone(new_parent_error_on_delete(Role.COORDENADOR, self.coord2, True))
        # filhos de um admin só passam para outro admin
        self.assertTrue(new_parent_error_on_delete(Role.ADMIN, self.coord, True))
        self.assertIsNone(new_parent_error_on_delete(Role.ADMIN, person(Role.ADMIN), True))
        # cabo nunca é responsável
        self.assertTrue(new_parent_error_on_delete(Role.COORDENADOR, self.cabo, True))


class GoalAndPasswordTests(SimpleTestCase):
    def test_goal_percent_and_tone(self):
        self.assertIsNone(goal_percent(10, None))
        self.assertIsNone(goal_percent(10, 0))
        self.assertEqual(goal_percent(5, 10), 50)
        self.assertEqual(goal_percent(30, 10), 300)
        self.assertEqual(goal_tone(None), "brand")
        self.assertEqual(goal_tone(100), "green")
        self.assertEqual(goal_tone(60), "brand")
        self.assertEqual(goal_tone(30), "yellow")
        self.assertEqual(goal_tone(10), "red")

    def test_temp_password_is_readable_and_random(self):
        values = {generate_temp_password() for _ in range(50)}
        self.assertGreater(len(values), 45)
        for pw in values:
            self.assertEqual(len(pw), 10)
            self.assertTrue(pw[:8].isalpha() and pw[8:].isdigit())
            self.assertFalse(set(pw) & set("ilIO01"))

    def test_access_message(self):
        msg = build_access_message(
            member_name="Maria da Silva",
            campaign_name="Ana Souza",
            role=Role.CABO,
            login_url="https://efind.test/login/",
            email="maria@x.com",
            password="Abcdefgh23",
            registration_url="https://efind.test/c/ABC/",
        )
        self.assertIn("Olá, Maria!", msg)
        self.assertIn("cabo eleitoral", msg)
        self.assertIn("Abcdefgh23", msg)
        self.assertIn("https://efind.test/c/ABC/", msg)
        reset = build_access_message(
            member_name="Maria",
            campaign_name="Ana",
            role=Role.CABO,
            login_url="u",
            email="e",
            password="p",
            registration_url="https://efind.test/c/ABC/",
            reset=True,
        )
        self.assertIn("redefinida", reset)

    def test_helpers(self):
        a = uuid.uuid4()
        self.assertTrue(rules.same_id(a, str(a)))
        self.assertFalse(rules.same_id(None, None))
        self.assertTrue(rules.is_campaign_role("CABO"))
        self.assertFalse(rules.is_campaign_role("SUPER_ADMIN"))
        self.assertFalse(rules.is_campaign_role(None))
