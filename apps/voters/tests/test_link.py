"""Meu link: link pessoal, QR Code, estatísticas, cartaz e roteamento do módulo."""

import re
from datetime import timedelta

from django.test import SimpleTestCase
from django.urls import resolve
from django.utils import timezone

from apps.accounts.models import RolePermission
from apps.core.constants import Role
from apps.voters.models import Voter

from .helpers import VoterTestCase, make_voter


class MyLinkTests(VoterTestCase):
    def test_page_shows_personal_link_qr_and_actions(self):
        self.login(self.cabo1)
        r = self.client.get("/painel/meu-link/")
        self.assertEqual(r.status_code, 200)
        link = f"/c/{self.cabo1.invite_code}/"
        self.assertContains(r, link)
        self.assertContains(r, "data:image/png;base64,")
        self.assertContains(r, "Baixar QR Code (PNG)")
        self.assertContains(r, "Copiar link")
        self.assertContains(r, f'data-copy="http://localhost:8000{link}"')
        self.assertContains(r, "Enviar pelo WhatsApp")
        self.assertContains(r, "https://wa.me/?text=")
        self.assertContains(r, "Imprimir cartaz")
        self.assertContains(r, 'download="qrcode-alfa.png"')
        # nunca mostra o link de outra pessoa
        self.assertNotContains(r, self.cabo2.invite_code)

    def test_stats_count_only_own_registrations(self):
        now = timezone.now()
        mine_today = make_voter(self.a, self.cabo1, neighborhood="Centro")
        old = make_voter(self.a, self.cabo1, neighborhood="Cambuí")
        Voter.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=3))
        older = make_voter(self.a, self.cabo1)
        Voter.objects.filter(pk=older.pk).update(created_at=now - timedelta(days=30))
        make_voter(self.a, self.cabo2)  # de outro cabo
        make_voter(self.b, self.admin_b)
        self.login(self.cabo1)
        r = self.client.get("/painel/eleitores/")  # só garante que a rede não muda as contas
        self.assertEqual(r.context["total"], 3)
        r = self.client.get("/painel/meu-link/")
        self.assertEqual(r.context["stats"], {"today": 1, "week": 2, "total": 3})
        self.assertEqual(len(r.context["recent"]), 3)
        self.assertEqual(r.context["recent"][0]["neighborhood"], mine_today.neighborhood)

    def test_goal_progress(self):
        self.cabo1.goal = 4
        self.cabo1.save()
        make_voter(self.a, self.cabo1)
        self.login(self.cabo1)
        r = self.client.get("/painel/meu-link/")
        self.assertEqual((r.context["goal"], r.context["goal_pct"], r.context["goal_remaining"]), (4, 25, 3))
        self.assertContains(r, "Faltam 3 cadastros para a meta")
        self.login(self.cabo2)
        self.assertContains(self.client.get("/painel/meu-link/"), "ainda não tem uma meta")

    def test_recent_list_requires_voter_view_permission(self):
        make_voter(self.a, self.cabo1, name="Pessoa Recente")
        self.login(self.cabo1)
        self.assertContains(self.client.get("/painel/meu-link/"), "Pessoa Recente")
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="eleitores").update(can_view=False)
        r = self.client.get("/painel/meu-link/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Pessoa Recente")
        self.assertNotContains(r, "Últimos cadastros")
        self.assertEqual(r.context["stats"]["total"], 1)

    def test_requires_meu_link_permission(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="meu_link").update(can_view=False)
        self.login(self.cabo1)
        self.assertEqual(self.client.get("/painel/meu-link/").status_code, 403)
        self.assertEqual(self.client.get("/painel/meu-link/cartaz/").status_code, 403)

    def test_poster(self):
        self.login(self.cabo1)
        r = self.client.get("/painel/meu-link/cartaz/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Alfa")
        self.assertContains(r, "12345")
        self.assertContains(r, "PXX")
        self.assertContains(r, "Aponte a câmera do celular e cadastre-se")
        self.assertContains(r, "@media print")
        self.assertContains(r, "window.print()")
        self.assertContains(r, f"localhost:8000/c/{self.cabo1.invite_code}")
        body = r.content.decode()
        svg = re.search(r"<svg[^>]*class=\"segno\".*?</svg>", body, re.S)
        self.assertIsNotNone(svg)
        self.assertIn("viewBox=", svg.group(0))  # escala com CSS para impressão nítida
        self.assertNotIn(self.cabo2.invite_code, body)

    def test_poster_uses_validated_brand_color(self):
        from apps.campaigns.models import Campaign

        Campaign.objects.filter(pk=self.a.pk).update(primary_color="javascript:1")
        self.login(self.cabo1)
        r = self.client.get("/painel/meu-link/cartaz/")
        self.assertNotContains(r, "javascript:1")
        self.assertContains(r, "#4f46e5")


class RoutingTests(SimpleTestCase):
    def test_root_urlconf_serves_every_module_route(self):
        for path, name in [
            ("/c/abc12345/", "voters:public_form"),
            ("/c/abc12345/obrigado/", "voters:public_thanks"),
            ("/c/abc12345/privacidade/", "voters:public_privacy"),
            ("/painel/eleitores/", "voters:list"),
            ("/painel/eleitores/novo/", "voters:create"),
            ("/painel/eleitores/exportar/", "voters:export"),
            ("/painel/eleitores/importar/", "voters:import"),
            ("/painel/meu-link/", "voters:my_link"),
            ("/painel/meu-link/cartaz/", "voters:my_link_poster"),
            ("/painel/eleitores/6f1c1d0e-1b0a-4f0e-9f57-5d3d2a1f0a11/", "voters:detail"),
        ]:
            match = resolve(path, urlconf="efind.urls")
            self.assertEqual(f"{match.namespace}:{match.url_name}", name, path)
