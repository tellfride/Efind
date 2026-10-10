"""Lista/hierarquia da equipe: lógica pura (árvore, filtros, ordenação, resumo) e a carga com contagens em 1 consulta."""

import datetime as dt
import uuid

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.core.constants import Role
from apps.team.listing import (
    MemberRow,
    build_tree,
    filter_rows,
    load_team_rows,
    parse_list_filters,
    roles_hint,
    sort_rows,
    summarize,
)

from .helpers import fast_hashers, make_campaign, make_user, make_voter


def mrow(name, role, parent=None, *, total=0, recent=0, goal=None, active=True, phone="", pk=None):
    return MemberRow(
        id=pk or uuid.uuid4(),
        name=name,
        email=f"{name.lower().replace(' ', '')}@x.com",
        phone=phone,
        role=role,
        parent_id=parent.id if parent else None,
        parent_name=parent.name if parent else "",
        is_active=active,
        goal=goal,
        region="",
        last_login=None,
        voters_total=total,
        voters_7d=recent,
    )


class PureListingTests(SimpleTestCase):
    def setUp(self):
        self.admin = mrow("Admin", Role.ADMIN, total=2)
        self.c1 = mrow("Carla", Role.COORDENADOR, self.admin, total=10, recent=3, goal=20)
        self.c2 = mrow("Bruno", Role.COORDENADOR, self.admin, total=0, active=False)
        self.k1 = mrow("Ana", Role.CABO, self.c1, total=30, recent=5, goal=20, phone="5511987654321")
        self.k2 = mrow("Zeca", Role.CABO, self.c1, total=4)
        self.k3 = mrow("Édson", Role.CABO, self.c2, total=1)
        self.rows = [self.k2, self.c2, self.k1, self.admin, self.k3, self.c1]

    def test_tree_structure_and_totals(self):
        tree = build_tree(self.rows)
        self.assertEqual(len(tree), 1)
        root = tree[0]
        self.assertEqual(root.row.name, "Admin")
        self.assertEqual([n.row.name for n in root.children], ["Carla", "Bruno"])  # ativos antes
        carla = root.children[0]
        self.assertEqual([n.row.name for n in carla.children], ["Ana", "Zeca"])
        self.assertEqual(carla.network_total, 10 + 30 + 4)
        self.assertEqual(root.network_total, 2 + 44 + 0 + 1)
        self.assertEqual(root.size, 6)

    def test_tree_roots_when_parent_not_visible(self):
        # visão do coordenador: ele e seus cabos (o admin não está entre os visíveis)
        tree = build_tree([self.c1, self.k1, self.k2])
        self.assertEqual([n.row.name for n in tree], ["Carla"])
        self.assertEqual(len(tree[0].children), 2)

    def test_tree_survives_cycles(self):
        a = mrow("A", Role.CABO)
        b = mrow("B", Role.CABO, a)
        a.parent_id = b.id  # dados inconsistentes
        tree = build_tree([a, b])
        names = sorted(n.row.name for n in tree)
        self.assertTrue(set(names) <= {"A", "B"} and names)

    def test_filters(self):
        def names(**kw):
            f = parse_list_filters(kw)
            return sorted(r.name for r in filter_rows(self.rows, f))

        self.assertEqual(names(papel="CABO"), ["Ana", "Zeca", "Édson"])
        self.assertEqual(names(status="inativos"), ["Bruno"])
        self.assertEqual(names(status="ativos", papel="COORDENADOR"), ["Carla"])
        self.assertEqual(names(q="edson"), ["Édson"])  # sem acento/maiúsculas
        self.assertEqual(names(q="98765"), ["Ana"])  # telefone
        self.assertEqual(names(q="12"), [])  # <4 dígitos não casa telefone
        self.assertEqual(names(coord=str(self.c1.id)), ["Ana", "Carla", "Zeca"])

    def test_filter_parsing_rejects_garbage(self):
        f = parse_list_filters({"papel": "SUPER_ADMIN", "status": "x", "ordem": "drop table", "q": "  oi  "}, set())
        self.assertEqual((f.role, f.status, f.sort, f.q), ("", "", "eleitores", "oi"))
        # coordenador de outra campanha / inexistente é descartado
        f = parse_list_filters({"coord": str(uuid.uuid4())}, {str(self.c1.id)})
        self.assertEqual(f.coordinator, "")
        self.assertEqual(f.active_count, 0)
        self.assertEqual(len(parse_list_filters({"q": "x" * 500}).q), 100)

    def test_sorting(self):
        def order(sort):
            return [r.name for r in sort_rows(self.rows, sort)]

        self.assertEqual(order("eleitores")[:3], ["Ana", "Carla", "Zeca"])
        self.assertEqual(order("menos")[0], "Bruno")
        self.assertEqual(order("7d")[:2], ["Ana", "Carla"])
        self.assertEqual(order("nome")[:3], ["Admin", "Ana", "Bruno"])
        meta = order("meta")
        self.assertEqual(meta[0], "Ana")  # 150% da meta
        self.assertEqual(meta[1], "Carla")  # 50%
        self.assertEqual(order("qualquer")[0], "Ana")  # padrão

    def test_summary(self):
        s = summarize(self.rows)
        self.assertEqual((s.total, s.admins, s.coordinators, s.cabos), (6, 1, 2, 3))
        self.assertEqual((s.active, s.inactive), (5, 1))
        self.assertEqual((s.voters, s.voters_7d), (47, 8))
        # ativos (não admin) sem cadastros em 7 dias: Zeca, Édson (Bruno está inativo)
        self.assertEqual(s.idle_7d, 2)
        self.assertEqual(roles_hint(s), "1 administrador · 2 coordenadores · 3 cabos")
        self.assertEqual(roles_hint(summarize([self.k1])), "1 cabo")

    def test_row_properties(self):
        self.assertEqual(self.k1.role_label, "Cabo eleitoral")
        self.assertEqual(self.c1.goal_percent, 50)
        self.assertEqual(self.k1.goal_tone, "green")
        self.assertIsNone(self.k2.goal_percent)


@fast_hashers
class LoadRowsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.camp = make_campaign("alfa")
        cls.other = make_campaign("beta")
        cls.admin = make_user(cls.camp, "admin@a.com", Role.ADMIN)
        cls.coord1 = make_user(cls.camp, "c1@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.coord2 = make_user(cls.camp, "c2@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.cabos = [make_user(cls.camp, f"k{i}@a.com", Role.CABO, parent=cls.coord1 if i % 2 else cls.coord2) for i in range(6)]
        cls.admin_b = make_user(cls.other, "admin@b.com", Role.ADMIN)
        n = 0
        for cabo in cls.cabos:
            for _ in range(2):
                n += 1
                make_voter(cls.camp, cabo, n)
        old = make_voter(cls.camp, cls.coord1, 99)
        type(old).objects.filter(pk=old.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
        make_voter(cls.other, cls.admin_b, 100)

    def test_counts_with_a_single_aggregate_query(self):
        with self.assertNumQueries(2):  # membros + UMA agregação de eleitores (sem N+1)
            rows = load_team_rows(self.admin)
        by_name = {r.email: r for r in rows}
        self.assertEqual(len(rows), 9)
        self.assertEqual(by_name["k0@a.com"].voters_total, 2)
        self.assertEqual(by_name["k0@a.com"].voters_7d, 2)
        self.assertEqual(by_name["c1@a.com"].voters_total, 1)
        self.assertEqual(by_name["c1@a.com"].voters_7d, 0)  # cadastro antigo
        self.assertEqual(by_name["admin@a.com"].voters_total, 0)
        self.assertEqual(by_name["k1@a.com"].parent_name, "C1")
        self.assertTrue(by_name["admin@a.com"].is_self)

    def test_coordinator_sees_only_own_network(self):
        rows = load_team_rows(self.coord1)
        emails = {r.email for r in rows}
        self.assertEqual(emails, {"c1@a.com", "k1@a.com", "k3@a.com", "k5@a.com"})
        self.assertEqual(sum(r.voters_total for r in rows), 1 + 6)

    def test_other_campaign_is_invisible(self):
        rows = load_team_rows(self.admin_b)
        self.assertEqual([r.email for r in rows], ["admin@b.com"])
        self.assertEqual(rows[0].voters_total, 1)
