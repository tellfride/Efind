"""Varredura de IDOR/BOLA entre módulos: percorre TODAS as rotas com <uuid:...> usando ids de objetos que o usuário
NÃO pode acessar (outra campanha e, na mesma campanha, fora do escopo hierárquico) por GET e POST.

Critérios: (1) nenhuma resposta 200 (nem formulário/página com dados do alvo); (2) nenhuma linha do banco muda.
Se um módulo novo adicionar rota com uuid, ela entra na varredura automaticamente.
"""

import re

from django.apps import apps as django_apps
from django.test import Client, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import Role
from apps.core.crypto import encrypt_json, random_token
from apps.dashboards.models import Dashboard
from apps.messaging.models import Broadcast, BroadcastMessage, MessageTemplate
from apps.voters.models import Voter
from apps.whatsapp.models import InboundMessage, WhatsAppConnection

PASSWORD = "Senha@12345"
KEY = "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc="
SNAPSHOT_MODELS = [
    "accounts.User", "accounts.RolePermission", "accounts.UserPermission", "campaigns.Campaign", "voters.Voter",
    "dashboards.Dashboard", "whatsapp.WhatsAppConnection", "whatsapp.InboundMessage",
    "messaging.MessageTemplate", "messaging.Broadcast", "messaging.BroadcastMessage",
]  # fmt: skip


def iter_routes(patterns, prefix=""):
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from iter_routes(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            yield route


def routes_with_uuid():
    return sorted({r for r in iter_routes(get_resolver().url_patterns) if "<uuid:" in r})


def snapshot():
    data = {}
    for label in SNAPSHOT_MODELS:
        model = django_apps.get_model(label)
        data[label] = sorted((repr(sorted(row.items(), key=lambda kv: kv[0])) for row in model.objects.values()))
    return data


def make_user(campaign, email, role, parent=None):
    return User.objects.create_user(email, PASSWORD, name=email.split("@")[0], role=role, campaign=campaign, parent=parent)


@override_settings(ENCRYPTION_KEY=KEY)
class IdorSweepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        def campaign(slug):
            c = Campaign.objects.create(slug=slug, candidate_name=slug, ballot_name=slug, office="VEREADOR", election_year=2026)
            bootstrap_campaign(c)
            return c

        cls.a, cls.b = campaign("alfa"), campaign("beta")
        cls.admin_a = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.coord1 = make_user(cls.a, "coord1@a.com", Role.COORDENADOR, cls.admin_a)
        cls.coord2 = make_user(cls.a, "coord2@a.com", Role.COORDENADOR, cls.admin_a)
        cls.cabo1 = make_user(cls.a, "cabo1@a.com", Role.CABO, cls.coord1)
        cls.cabo2 = make_user(cls.a, "cabo2@a.com", Role.CABO, cls.coord2)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.cabo_b = make_user(cls.b, "cabo@b.com", Role.CABO, cls.admin_b)
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD)

        def voter(c, owner, n):
            return Voter.objects.create(campaign=c, registered_by=owner, name=f"Apoiador {n}", phone=f"5511900000{n:03d}", whatsapp_opt_in=True, consent_text="x")

        cls.voters_b = [voter(cls.b, cls.cabo_b, 1), voter(cls.b, cls.admin_b, 2)]
        cls.voter_a2 = voter(cls.a, cls.cabo2, 3)  # fora do escopo de cabo1 e de coord1
        cls.voter_a_admin = voter(cls.a, cls.admin_a, 4)  # fora do escopo de coordenadores/cabos

        def conn(c):
            return WhatsAppConnection.objects.create(campaign=c, name="c", provider="SANDBOX", status="CONNECTED", credentials=encrypt_json({}), webhook_token=random_token())

        def tpl_dash_broadcast(c, owner, name):
            t = MessageTemplate.objects.create(campaign=c, name=name, body="Oi {{nome}}")
            d = Dashboard.objects.create(campaign=c, owner=owner, name=name, widgets=[], shared=False)
            b = Broadcast.objects.create(campaign=c, name=name, created_by=owner, template=t, filters={})
            BroadcastMessage.objects.create(broadcast=b, campaign=c, phone="5511900009999", rendered_body="x")
            return t, d, b

        cls.conn_b, cls.conn_a = conn(cls.b), conn(cls.a)
        cls.tpl_b, cls.dash_b, cls.bc_b = tpl_dash_broadcast(cls.b, cls.admin_b, "b")
        cls.tpl_a, cls.dash_a, cls.bc_a = tpl_dash_broadcast(cls.a, cls.admin_a, "a")
        InboundMessage.objects.create(campaign=cls.b, from_phone="5511900000001", body="oi")

    # --- alvos --------------------------------------------------------------------------------------
    def other_campaign_ids(self):
        objs = [self.b, self.admin_b, self.cabo_b, *self.voters_b, self.conn_b, self.tpl_b, self.dash_b, self.bc_b]
        return [str(o.pk) for o in objs]

    def same_campaign_out_of_scope_ids(self):
        # usuários/apoiadores fora do escopo e objetos privados de outro usuário da MESMA campanha
        return [str(o.pk) for o in (self.voter_a2, self.voter_a_admin, self.admin_a, self.cabo2, self.coord2, self.dash_a, self.bc_a)]

    # --- varredura ----------------------------------------------------------------------------------
    def sweep(self, email, ids, extra_note=""):
        client = Client()
        self.assertTrue(client.login(username=email, password=PASSWORD), email)
        routes = routes_with_uuid()
        self.assertGreater(len(routes), 25, "poucas rotas com uuid encontradas — o enumerador quebrou?")
        before = snapshot()
        leaks = []
        for route in routes:
            for target in ids:
                url = "/" + re.sub(r"<uuid:\w+>", target, route)
                if "<" in url:
                    continue  # rota com outro tipo de conversor
                for method in ("get", "post"):
                    response = getattr(client, method)(url, follow=False)
                    if response.status_code == 200:
                        leaks.append(f"{email} {method.upper()} {url} -> 200")
        after = snapshot()
        changed = [label for label in SNAPSHOT_MODELS if before[label] != after[label]]
        self.assertEqual(leaks, [], f"respostas 200 em objetos fora do alcance ({extra_note}):\n" + "\n".join(leaks[:15]))
        self.assertEqual(changed, [], f"dados alterados por requisições fora do alcance: {changed}")

    def test_admin_cannot_touch_other_campaign(self):
        self.sweep("admin@a.com", self.other_campaign_ids(), "ADMIN da campanha A × campanha B")

    def test_coordinator_cannot_touch_other_campaign_or_out_of_scope(self):
        self.sweep("coord1@a.com", self.other_campaign_ids() + self.same_campaign_out_of_scope_ids(), "COORDENADOR")

    def test_cabo_cannot_touch_other_campaign_or_out_of_scope(self):
        self.sweep("cabo1@a.com", self.other_campaign_ids() + self.same_campaign_out_of_scope_ids(), "CABO")

    def test_super_admin_never_gets_voter_pages(self):
        client = Client()
        self.assertTrue(client.login(username="super@x.com", password=PASSWORD))
        for voter in [*self.voters_b, self.voter_a2]:
            for path in (f"/painel/apoiadores/{voter.pk}/", f"/painel/apoiadores/{voter.pk}/excluir/"):
                self.assertNotEqual(client.get(path).status_code, 200, path)

    def test_anonymous_gets_no_panel_or_api_page(self):
        client = Client()
        for route in routes_with_uuid():
            if route.startswith(("super/", "painel/", "api/painel/")):
                url = "/" + re.sub(r"<uuid:\w+>", str(self.voter_a2.pk), route)
                if "<" in url:
                    continue
                self.assertIn(client.get(url).status_code, (302, 401, 403, 404, 405), url)

    def test_positive_control_same_urls_work_for_authorized_users(self):
        """Garante que a varredura não é vacuosa: os mesmos formatos de URL funcionam quando há acesso legítimo."""
        client = Client()
        self.assertTrue(client.login(username="admin@a.com", password=PASSWORD))
        legit = [
            f"/painel/apoiadores/{self.voter_a2.pk}/",
            f"/painel/equipe/{self.cabo2.pk}/",
            f"/painel/dashboards/{self.dash_a.pk}/",
            f"/painel/mensagens/modelos/{self.tpl_a.pk}/",
            f"/painel/mensagens/disparos/{self.bc_a.pk}/",
            f"/painel/whatsapp/{self.conn_a.pk}/editar/",
        ]
        for url in legit:
            self.assertEqual(client.get(url).status_code, 200, url)
        # e o mesmo caminho com um id de OUTRA campanha é negado
        self.assertEqual(client.get(f"/painel/apoiadores/{self.voters_b[0].pk}/").status_code, 404)
        self.assertEqual(client.get(f"/painel/equipe/{self.cabo_b.pk}/").status_code, 404)
