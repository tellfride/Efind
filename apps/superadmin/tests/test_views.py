"""Views do super admin: acesso, páginas, fluxos de escrita, isolamento e privacidade."""

import datetime as dt
import uuid

from django.contrib.messages import get_messages
from django.contrib.sessions.models import Session
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.auditlog.models import AuditLog
from apps.auditlog.service import audit
from apps.campaigns.models import Campaign
from apps.core.constants import BroadcastStatus, CampaignStatus, ConnectionStatus, MessageStatus, Role, label_of
from apps.messaging.models import Broadcast, BroadcastMessage
from apps.superadmin import selectors
from apps.voters.models import Voter
from apps.whatsapp.models import WhatsAppConnection

from .helpers import (
    PASSWORD,
    campaign_edit_data,
    campaign_post_data,
    client_for,
    fast_hasher,
    make_campaign,
    make_super,
    make_user,
    make_voter,
)


def msgs(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def url(name, *args):
    return reverse(f"superadmin:{name}", args=args)


@fast_hasher
class BaseCase(TestCase):
    """Duas campanhas, equipe completa em `alfa`, eleitores com nomes reconhecíveis e um super admin logado."""

    @classmethod
    def setUpTestData(cls):
        cls.super = make_super("super@efind.test", name="Super Dono")
        cls.a = make_campaign("alfa", ballot_name="Alfa Urna", party="PSD", city="Campinas", state="SP", ballot_number="12345")
        cls.b = make_campaign("beta", ballot_name="Beta Urna", party="PT", city="Santos", state="SP", status=CampaignStatus.SUSPENDED)
        cls.admin_a = make_user(cls.a, "admin@a.test", Role.ADMIN, name="Admin Alfa")
        cls.coord_a = make_user(cls.a, "coord@a.test", Role.COORDENADOR, parent=cls.admin_a)
        cls.cabo_a = make_user(cls.a, "cabo@a.test", Role.CABO, parent=cls.coord_a)
        cls.admin_b = make_user(cls.b, "admin@b.test", Role.ADMIN, name="Admin Beta")
        now = timezone.now()
        cls.v1 = make_voter(cls.a, cls.cabo_a, 1, whatsapp_opt_in=True, consent_at=now)
        cls.v2 = make_voter(cls.a, cls.cabo_a, 2, whatsapp_opt_in=True, consent_at=now, opt_out_at=now)
        cls.v3 = make_voter(cls.a, cls.coord_a, 3, whatsapp_opt_in=True)  # sem consentimento LGPD
        cls.v4 = make_voter(cls.b, cls.admin_b, 4)
        Voter.objects.filter(pk=cls.v2.pk).update(created_at=now - dt.timedelta(days=10))
        Voter.objects.filter(pk=cls.v3.pk).update(created_at=now - dt.timedelta(days=40))

    def setUp(self):
        self.client = client_for(self.super)


# ---------------------------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------------------------


class AccessControlTests(BaseCase):
    def routes(self):
        """(nome, args, métodos) de TODAS as rotas /super/ do módulo."""
        pk, uid = self.a.pk, self.admin_a.pk
        return [
            ("home", [], ["get"]),
            ("campaigns", [], ["get"]),
            ("campaign_create", [], ["get", "post"]),
            ("campaign_detail", [pk], ["get"]),
            ("campaign_update", [pk], ["post"]),
            ("campaign_suspend", [pk], ["post"]),
            ("campaign_activate", [pk], ["post"]),
            ("campaign_delete", [pk], ["post"]),
            ("campaign_admin_create", [pk], ["post"]),
            ("campaign_admin_reset_password", [pk, uid], ["post"]),
            ("campaign_admin_activate", [pk, uid], ["post"]),
            ("campaign_admin_deactivate", [pk, uid], ["post"]),
            ("users", [], ["get"]),
            ("user_create", [], ["post"]),
            ("user_reset_password", [self.super.pk], ["post"]),
            ("user_activate", [self.super.pk], ["post"]),
            ("user_deactivate", [self.super.pk], ["post"]),
            ("audit", [], ["get"]),
        ]

    def snapshot(self):
        return (
            list(Campaign.objects.order_by("slug").values_list("slug", "status", "city")),
            list(User.objects.order_by("email").values_list("email", "is_active", "password")),
            Voter.objects.count(),
            AuditLog.objects.count(),
        )

    def test_anonymous_is_sent_to_login(self):
        client = Client()
        before = self.snapshot()
        for name, args, methods in self.routes():
            for method in methods:
                response = getattr(client, method)(url(name, *args), {"confirm_slug": self.a.slug})
                self.assertEqual(response.status_code, 302, (name, method))
                self.assertTrue(response["Location"].startswith("/login/?next="), (name, method, response["Location"]))
        self.assertEqual(before, self.snapshot())

    def test_campaign_users_never_reach_super_routes(self):
        before = self.snapshot()
        for user in (self.admin_a, self.coord_a, self.cabo_a):
            client = client_for(user)
            for name, args, methods in self.routes():
                for method in methods:
                    response = getattr(client, method)(url(name, *args), {"confirm_slug": self.a.slug, "name": "X"})
                    self.assertIn(response.status_code, (302, 403), (user.email, name, method))
                    if response.status_code == 302:
                        self.assertEqual(response["Location"], "/painel/", (user.email, name, method))
        # administrador de campanha suspensa: a sessão é encerrada antes de qualquer view
        suspended = client_for(self.admin_b).get(url("home"))
        self.assertEqual((suspended.status_code, suspended["Location"]), (302, "/login/"))
        self.assertEqual(before, self.snapshot())

    def test_write_routes_reject_get(self):
        for name, args, methods in self.routes():
            if "get" in methods:
                continue
            self.assertEqual(self.client.get(url(name, *args)).status_code, 405, name)

    def test_unknown_campaign_is_404(self):
        ghost = uuid.uuid4()
        self.assertEqual(self.client.get(url("campaign_detail", ghost)).status_code, 404)
        for name in ("campaign_update", "campaign_suspend", "campaign_activate", "campaign_delete", "campaign_admin_create"):
            self.assertEqual(self.client.post(url(name, ghost), {}).status_code, 404, name)

    def test_super_admin_does_not_reach_voter_pages(self):
        for path in ("/painel/", "/painel/eleitores/", f"/painel/eleitores/{self.v1.pk}/", "/painel/mapa/", "/painel/equipe/"):
            response = self.client.get(path)
            self.assertIn(response.status_code, (302, 403, 404), path)
            if response.status_code == 302:
                self.assertEqual(response["Location"], "/super/", path)


# ---------------------------------------------------------------------------------------------
# Visão geral e lista
# ---------------------------------------------------------------------------------------------


class OverviewAndListTests(BaseCase):
    def test_home_shows_kpis(self):
        response = self.client.get(url("home"))
        self.assertEqual(response.status_code, 200)
        overview = response.context["overview"]
        self.assertEqual(overview["campaigns_total"], 2)
        self.assertEqual(overview["campaigns_active"], 1)
        self.assertEqual(overview["campaigns_suspended"], 1)
        self.assertEqual(overview["campaign_users"], 4)  # o super admin não conta
        self.assertEqual(overview["voters_total"], 4)
        self.assertEqual(overview["voters_last7"], 2)  # v2 (10 dias) e v3 (40 dias) ficam de fora
        self.assertContains(response, "Alfa Urna")
        self.assertContains(response, "Beta Urna")
        self.assertContains(response, reverse("superadmin:campaign_create"))
        self.assertEqual({c.pk: (c.user_count, c.voter_count) for c in overview["recent"]}, {self.a.pk: (3, 3), self.b.pk: (1, 1)})

    def test_home_empty_state(self):
        Voter.objects.all().delete()
        Campaign.objects.all().delete()
        response = self.client.get(url("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhuma campanha ainda")

    def test_list_columns_and_counts(self):
        response = self.client.get(url("campaigns"))
        self.assertEqual(response.status_code, 200)
        rows = {c.pk: c for c in response.context["campaigns"]}
        self.assertEqual((rows[self.a.pk].user_count, rows[self.a.pk].voter_count), (3, 3))
        self.assertEqual(rows[self.a.pk].office_label, "Vereador(a)")
        self.assertEqual(rows[self.a.pk].place, "Campinas/SP")
        self.assertContains(response, "Ativa")
        self.assertContains(response, "Suspensa")

    def test_list_search_and_status_filter(self):
        def names(**params):
            response = self.client.get(url("campaigns"), params)
            self.assertEqual(response.status_code, 200)
            return {c.slug for c in response.context["campaigns"]}

        self.assertEqual(names(q="alfa"), {"alfa"})
        self.assertEqual(names(q="PT"), {"beta"})
        self.assertEqual(names(q="campinas"), {"alfa"})
        self.assertEqual(names(q="Alfa", status="SUSPENDED"), set())
        self.assertEqual(names(status="SUSPENDED"), {"beta"})
        self.assertEqual(names(status="ACTIVE"), {"alfa"})
        self.assertEqual(names(status="INVALIDO"), {"alfa", "beta"})  # filtro inválido é ignorado
        self.assertContains(self.client.get(url("campaigns"), {"q": "nada-disso"}), "Nenhuma campanha encontrada")

    def test_list_pagination_is_25(self):
        Campaign.objects.bulk_create(
            [
                Campaign(slug=f"extra-{i:02d}", candidate_name="Extra", ballot_name=f"Extra {i:02d}", office="VEREADOR", election_year=2026)
                for i in range(28)
            ]
        )
        first = self.client.get(url("campaigns"))
        self.assertEqual(len(first.context["campaigns"]), 25)
        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        second = self.client.get(url("campaigns"), {"page": 2})
        self.assertEqual(len(second.context["campaigns"]), 5)
        self.assertEqual(self.client.get(url("campaigns"), {"page": "lixo"}).status_code, 200)

    def test_query_count_does_not_grow_with_campaigns(self):
        def queries(name):
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get(url(name)).status_code, 200)
            return len(ctx)

        base = {name: queries(name) for name in ("home", "campaigns")}
        for i in range(6):
            campaign = make_campaign(f"extra-{i}")
            owner = make_user(campaign, f"adm{i}@x.test", Role.ADMIN)
            make_voter(campaign, owner, 100 + i)
        self.assertEqual(base, {name: queries(name) for name in ("home", "campaigns")})

    def test_user_content_is_escaped(self):
        evil = "<img src=x onerror=alert(1)>"
        campaign = make_campaign("evil", ballot_name=evil)
        for response in (self.client.get(url("home")), self.client.get(url("campaigns")), self.client.get(url("campaign_detail", campaign.pk))):
            self.assertNotContains(response, evil)
            self.assertContains(response, "&lt;img src=x onerror=alert(1)&gt;")


# ---------------------------------------------------------------------------------------------
# Criação
# ---------------------------------------------------------------------------------------------


class CreateCampaignViewTests(BaseCase):
    def test_form_renders_both_sections(self):
        response = self.client.get(url("campaign_create"))
        self.assertEqual(response.status_code, 200)
        for text in ("Candidato e campanha", "Primeiro administrador", 'name="admin-email"', 'name="ballot_name"', 'type="color"'):
            self.assertContains(response, text)
        self.assertContains(response, f'value="{timezone.localdate().year}"')
        self.assertContains(response, "#4f46e5")

    def test_creates_campaign_and_shows_credentials_once(self):
        response = self.client.post(url("campaign_create"), campaign_post_data())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "superadmin/campaign_created.html")
        creds = response.context["creds"]
        campaign = Campaign.objects.get(slug="joao-silva")
        admin = User.objects.get(email="maria.admin@exemplo.com")
        self.assertEqual((admin.role, admin.campaign_id, admin.phone), (Role.ADMIN, campaign.pk, "5519987654321"))
        self.assertEqual((campaign.city, campaign.primary_color, campaign.voter_goal), ("Campinas", "#112233", 5000))
        # credenciais exibidas na resposta do POST, com botões de copiar
        self.assertContains(response, creds.password)
        self.assertContains(response, "maria.admin@exemplo.com")
        self.assertContains(response, creds.login_url)
        self.assertContains(response, f'data-copy="{creds.password}"')
        self.assertContains(response, "não será exibida novamente")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(admin.check_password(creds.password))
        self.assertTrue(Client().login(username="maria.admin@exemplo.com", password=creds.password))
        # nada de senha em sessão, auditoria ou nas páginas seguintes
        for session in Session.objects.all():
            self.assertNotIn(creds.password, str(session.get_decoded()))
        self.assertFalse(any(creds.password in str(log.details) for log in AuditLog.objects.all()))
        self.assertNotContains(self.client.get(url("campaign_detail", campaign.pk)), creds.password)
        self.assertNotContains(self.client.get(url("campaigns")), creds.password)
        self.assertEqual(
            set(AuditLog.objects.filter(campaign=campaign).values_list("action", flat=True)), {"campaign.create", "user.create"}
        )

    def test_created_page_shows_election_year_without_thousand_separator(self):
        # Regressão (QA no navegador): com USE_THOUSAND_SEPARATOR o ano saía como "2.026"
        response = self.client.post(url("campaign_create"), campaign_post_data(election_year="2026"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<dd class=\"col-span-2\">2026</dd>", html=False)
        self.assertNotContains(response, "2.026")

    def test_explicit_password_is_honoured(self):
        response = self.client.post(url("campaign_create"), campaign_post_data(**{"admin-password": "Minha#Senha2026"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Minha#Senha2026")
        self.assertContains(response, "Senha</dt>")
        self.assertTrue(Client().login(username="maria.admin@exemplo.com", password="Minha#Senha2026"))

    def test_bootstrap_runs(self):
        self.client.post(url("campaign_create"), campaign_post_data())
        campaign = Campaign.objects.get(slug="joao-silva")
        self.assertGreater(campaign.role_permissions.count(), 0)
        self.assertGreater(campaign.dashboards.count(), 0)

    def test_duplicate_slug_gets_suffix(self):
        self.client.post(url("campaign_create"), campaign_post_data())
        self.client.post(url("campaign_create"), campaign_post_data(**{"admin-email": "outra@exemplo.com"}))
        self.assertEqual(sorted(Campaign.objects.filter(slug__startswith="joao-silva").values_list("slug", flat=True)), ["joao-silva", "joao-silva-2"])

    def test_duplicate_email_is_a_friendly_field_error_and_creates_nothing(self):
        before = (Campaign.objects.count(), User.objects.count())
        response = self.client.post(url("campaign_create"), campaign_post_data(**{"admin-email": "ADMIN@A.TEST"}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "superadmin/campaign_form.html")
        self.assertContains(response, "Este e-mail já está cadastrado")
        self.assertIn("email", response.context["admin_form"].errors)
        self.assertEqual(before, (Campaign.objects.count(), User.objects.count()))
        # dados digitados são preservados, a senha não
        self.assertContains(response, "João Silva")
        self.assertNotContains(response, "Minha#Senha")

    def test_invalid_campaign_shows_all_errors(self):
        before = Campaign.objects.count()
        response = self.client.post(
            url("campaign_create"),
            campaign_post_data(primary_color="vermelho", ballot_number="1", office="", ballot_name="", **{"admin-email": "invalido"}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Campaign.objects.count(), before)
        self.assertEqual(set(response.context["form"].errors), {"primary_color", "ballot_number", "office", "ballot_name"})
        self.assertIn("email", response.context["admin_form"].errors)  # os dois formulários são validados juntos
        self.assertIn("Verifique os campos destacados.", msgs(response))

    def test_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.super)
        self.assertEqual(client.post(url("campaign_create"), campaign_post_data()).status_code, 403)
        self.assertFalse(Campaign.objects.filter(slug="joao-silva").exists())


# ---------------------------------------------------------------------------------------------
# Detalhe, edição, status e exclusão
# ---------------------------------------------------------------------------------------------


class CampaignDetailTests(BaseCase):
    def test_detail_renders_all_tabs(self):
        response = self.client.get(url("campaign_detail", self.a.pk))
        self.assertEqual(response.status_code, 200)
        for text in ("Dados", "Administradores", "Uso", "Zona de perigo", "Admin Alfa", "admin@a.test", "Nunca acessou", "Suspender"):
            self.assertContains(response, text)
        self.assertContains(response, 'data-tabs="dados,administradores,uso"')
        self.assertContains(response, "js/superadmin/super.js")
        self.assertEqual([u.email for u in response.context["admins"]], ["admin@a.test"])  # só ADMIN, só desta campanha
        self.assertNotContains(response, "coord@a.test")
        self.assertNotContains(response, "admin@b.test")

    def test_suspended_campaign_shows_reactivate(self):
        response = self.client.get(url("campaign_detail", self.b.pk))
        self.assertContains(response, "Campanha suspensa")
        self.assertContains(response, url("campaign_activate", self.b.pk))
        self.assertNotContains(response, url("campaign_suspend", self.b.pk))

    def test_usage_is_aggregate_only(self):
        WhatsAppConnection.objects.create(campaign=self.a, name="Sim", provider="SANDBOX", status=ConnectionStatus.CONNECTED, credentials="x", webhook_token="t1")
        WhatsAppConnection.objects.create(campaign=self.a, name="Rascunho", provider="SANDBOX", credentials="x", webhook_token="t2")
        WhatsAppConnection.objects.create(campaign=self.b, name="Outra", provider="SANDBOX", status=ConnectionStatus.CONNECTED, credentials="x", webhook_token="t3")
        sent = Broadcast.objects.create(campaign=self.a, name="Enviado", status=BroadcastStatus.COMPLETED)
        Broadcast.objects.create(campaign=self.a, name="Rascunho", status=BroadcastStatus.DRAFT)
        Broadcast.objects.create(campaign=self.b, name="Outra campanha", status=BroadcastStatus.RUNNING)
        for status in (MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.FAILED, MessageStatus.PENDING):
            BroadcastMessage.objects.create(broadcast=sent, campaign=self.a, phone="5511900000999", rendered_body="oi segredo", status=status)
        self.coord_a.is_active = False
        self.coord_a.save()

        usage = selectors.campaign_usage(self.a)
        self.assertEqual(usage["voters"]["total"], 3)
        self.assertEqual(usage["voters"]["last7"], 1)
        self.assertEqual(usage["voters"]["last30"], 2)
        self.assertEqual(usage["voters"]["messageable"], 1)  # v1: opt-in + consentimento + sem descadastro
        self.assertEqual(usage["voters"]["opted_out"], 1)
        self.assertEqual(usage["connections"], {"total": 2, "connected": 1})
        self.assertEqual(usage["broadcasts_total"], 2)
        self.assertEqual(usage["messages"], {"sent": 2, "failed": 1})
        team = {row["label"]: (row["active"], row["inactive"]) for row in usage["team"]}
        self.assertEqual(team[label_of(Role, Role.ADMIN)], (1, 0))
        self.assertEqual(team[label_of(Role, Role.COORDENADOR)], (0, 1))
        self.assertEqual(team[label_of(Role, Role.CABO)], (1, 0))
        self.assertEqual(usage["team_total"], 3)

        response = self.client.get(url("campaign_detail", self.a.pk))
        self.assertContains(response, "Aptos a receber WhatsApp")
        # nenhum dado pessoal de eleitor ou conteúdo de mensagem chega à página
        for secret in ("Eleitora Sigilosa", "5511900000", "(11) 90000", "oi segredo", "5511900000999"):
            self.assertNotContains(response, secret)

    def test_update_changes_fields_and_keeps_slug(self):
        response = self.client.post(url("campaign_update", self.a.pk), campaign_edit_data(self.a, city="Santos", ballot_name="Alfa Nova", primary_color="#AABBCC"))
        self.assertRedirects(response, url("campaign_detail", self.a.pk), fetch_redirect_response=False)
        self.a.refresh_from_db()
        self.assertEqual((self.a.city, self.a.ballot_name, self.a.primary_color, self.a.slug), ("Santos", "Alfa Nova", "#aabbcc", "alfa"))
        self.assertIn("Dados da campanha atualizados.", msgs(response))
        log = AuditLog.objects.get(action="campaign.update")
        self.assertEqual(log.campaign_id, self.a.pk)
        self.assertEqual(set(log.details["fields"]), {"city", "ballot_name", "primary_color"})
        self.assertNotIn("Santos", str(log.details))  # só nomes de campos, nunca valores

    def test_update_without_changes_is_a_noop(self):
        response = self.client.post(url("campaign_update", self.a.pk), campaign_edit_data(self.a))
        self.assertEqual(response.status_code, 302)
        self.assertIn("Nenhuma alteração para salvar.", msgs(response))
        self.assertFalse(AuditLog.objects.filter(action="campaign.update").exists())

    def test_update_with_invalid_data_rerenders_with_errors(self):
        response = self.client.post(url("campaign_update", self.a.pk), campaign_edit_data(self.a, primary_color="azul", city="Outra"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("primary_color", response.context["form"].errors)
        self.assertContains(response, "Cor inválida")
        self.a.refresh_from_db()
        self.assertEqual((self.a.city, self.a.primary_color), ("Campinas", "#4f46e5"))

    def test_update_cannot_change_status_or_slug(self):
        self.client.post(url("campaign_update", self.a.pk), campaign_edit_data(self.a, city="Outra", slug="hack", status="SUSPENDED", logo_url="x"))
        self.a.refresh_from_db()
        self.assertEqual((self.a.slug, self.a.status, self.a.logo_url), ("alfa", CampaignStatus.ACTIVE, ""))

    def test_suspend_blocks_the_team_and_reactivate_restores(self):
        admin_client = client_for(self.admin_a)
        self.assertEqual(admin_client.get("/painel/perfil/").status_code, 200)
        response = self.client.post(url("campaign_suspend", self.a.pk))
        self.assertRedirects(response, url("campaign_detail", self.a.pk), fetch_redirect_response=False)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, CampaignStatus.SUSPENDED)
        blocked = admin_client.get("/painel/perfil/")
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(blocked["Location"], "/login/")
        # novo login também é recusado enquanto a campanha estiver suspensa
        attempt = Client().post("/login/", {"email": "admin@a.test", "password": PASSWORD})
        self.assertContains(attempt, "suspensa")
        self.assertNotIn("_auth_user_id", attempt.client.session)
        # reativar
        response = self.client.post(url("campaign_activate", self.a.pk))
        self.assertEqual(response.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, CampaignStatus.ACTIVE)
        self.assertEqual(client_for(self.admin_a).get("/painel/perfil/").status_code, 200)
        self.assertEqual(
            list(AuditLog.objects.filter(campaign=self.a, action__startswith="campaign.").order_by("created_at").values_list("action", flat=True)),
            ["campaign.suspend", "campaign.activate"],
        )

    def test_suspend_twice_is_harmless(self):
        self.client.post(url("campaign_suspend", self.a.pk))
        response = self.client.post(url("campaign_suspend", self.a.pk))
        self.assertIn("A campanha já está suspensa.", msgs(response))
        self.assertEqual(AuditLog.objects.filter(action="campaign.suspend").count(), 1)

    def test_delete_requires_the_exact_slug(self):
        for typed in ("", "alfa-2", "ALFA", self.a.ballot_name):
            response = self.client.post(url("campaign_delete", self.a.pk), {"confirm_slug": typed})
            self.assertEqual(response.status_code, 200, typed)
            self.assertIn("confirm_slug", response.context["delete_form"].errors)
        self.assertTrue(Campaign.objects.filter(pk=self.a.pk).exists())
        self.assertEqual(Voter.objects.filter(campaign=self.a).count(), 3)
        self.assertFalse(AuditLog.objects.filter(action="campaign.delete").exists())

    def test_delete_with_voters_removes_everything_of_that_campaign_only(self):
        response = self.client.post(url("campaign_delete", self.a.pk), {"confirm_slug": "alfa"})
        self.assertRedirects(response, url("campaigns"), fetch_redirect_response=False)
        self.assertFalse(Campaign.objects.filter(pk=self.a.pk).exists())
        self.assertFalse(Voter.objects.filter(campaign_id=self.a.pk).exists())
        self.assertFalse(User.objects.filter(campaign_id=self.a.pk).exists())
        self.assertTrue(Campaign.objects.filter(pk=self.b.pk).exists())
        self.assertEqual(Voter.objects.filter(campaign=self.b).count(), 1)
        self.assertTrue(User.objects.filter(pk=self.admin_b.pk).exists())
        log = AuditLog.objects.get(action="campaign.delete")
        self.assertIsNone(log.campaign_id)
        self.assertEqual(log.details, {"slug": "alfa", "ballot_name": "Alfa Urna"})
        self.assertEqual(self.client.get(url("campaign_detail", self.a.pk)).status_code, 404)

    def test_cannot_delete_another_campaign_by_typing_a_different_slug(self):
        response = self.client.post(url("campaign_delete", self.a.pk), {"confirm_slug": self.b.slug})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Campaign.objects.filter(pk__in=[self.a.pk, self.b.pk]).count(), 2)


# ---------------------------------------------------------------------------------------------
# Administradores da campanha
# ---------------------------------------------------------------------------------------------


class CampaignAdminTests(BaseCase):
    def admin_data(self, **overrides):
        data = {"name": "Segundo Admin", "email": " Segundo@Exemplo.com", "phone": "", "password": ""}
        data.update(overrides)
        return data

    def test_add_admin_shows_credentials(self):
        response = self.client.post(url("campaign_admin_create", self.a.pk), self.admin_data())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "superadmin/credentials.html")
        creds = response.context["creds"]
        user = User.objects.get(email="segundo@exemplo.com")
        self.assertEqual((user.role, user.campaign_id), (Role.ADMIN, self.a.pk))
        self.assertContains(response, creds.password)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(user.check_password(creds.password))
        log = AuditLog.objects.get(action="user.create", entity_id=str(user.pk))
        self.assertEqual(log.campaign_id, self.a.pk)
        self.assertNotIn(creds.password, str(log.details))

    def test_add_admin_duplicate_email_rerenders_the_admins_tab(self):
        response = self.client.post(url("campaign_admin_create", self.a.pk), self.admin_data(email="COORD@a.test"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "superadmin/campaign_detail.html")
        self.assertEqual(response.context["active_tab"], "administradores")
        self.assertContains(response, "Este e-mail já está cadastrado")
        self.assertEqual(User.objects.filter(campaign=self.a, role=Role.ADMIN).count(), 1)

    def test_reset_password(self):
        old_hash = self.admin_a.password
        response = self.client.post(url("campaign_admin_reset_password", self.a.pk, self.admin_a.pk))
        self.assertEqual(response.status_code, 200)
        creds = response.context["creds"]
        self.admin_a.refresh_from_db()
        self.assertNotEqual(self.admin_a.password, old_hash)
        self.assertTrue(self.admin_a.check_password(creds.password))
        self.assertContains(response, creds.password)
        self.assertEqual(AuditLog.objects.filter(action="user.password_reset", campaign=self.a).count(), 1)
        # a página do detalhe não repete a senha
        self.assertNotContains(self.client.get(url("campaign_detail", self.a.pk)), creds.password)

    def test_deactivate_and_activate(self):
        second = make_user(self.a, "admin2@a.test", Role.ADMIN)
        response = self.client.post(url("campaign_admin_deactivate", self.a.pk, second.pk))
        self.assertRedirects(response, url("campaign_detail", self.a.pk) + "#administradores", fetch_redirect_response=False)
        second.refresh_from_db()
        self.assertFalse(second.is_active)
        self.assertFalse(Client().login(username="admin2@a.test", password=PASSWORD))
        self.assertContains(self.client.get(url("campaign_detail", self.a.pk)), "Desativado")
        self.client.post(url("campaign_admin_activate", self.a.pk, second.pk))
        second.refresh_from_db()
        self.assertTrue(second.is_active)
        self.assertTrue(Client().login(username="admin2@a.test", password=PASSWORD))
        self.assertEqual(AuditLog.objects.filter(action__in=["user.deactivate", "user.activate"]).count(), 2)

    def test_last_active_admin_cannot_be_deactivated(self):
        response = self.client.post(url("campaign_admin_deactivate", self.a.pk, self.admin_a.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("pelo menos um administrador ativo" in m for m in msgs(response)))
        self.admin_a.refresh_from_db()
        self.assertTrue(self.admin_a.is_active)

    def test_ids_from_other_campaigns_or_roles_are_404(self):
        old_hash = User.objects.get(pk=self.admin_b.pk).password
        cases = [
            (self.a.pk, self.admin_b.pk),  # administrador de OUTRA campanha
            (self.a.pk, self.coord_a.pk),  # não é ADMIN
            (self.a.pk, self.cabo_a.pk),
            (self.a.pk, self.super.pk),  # super admin
            (self.b.pk, self.admin_a.pk),  # campanha trocada
            (self.a.pk, uuid.uuid4()),
        ]
        for name in ("campaign_admin_reset_password", "campaign_admin_deactivate", "campaign_admin_activate"):
            for campaign_pk, user_pk in cases:
                self.assertEqual(self.client.post(url(name, campaign_pk, user_pk)).status_code, 404, (name, campaign_pk, user_pk))
        self.assertEqual(User.objects.get(pk=self.admin_b.pk).password, old_hash)
        self.assertTrue(User.objects.get(pk=self.admin_b.pk).is_active)
        self.assertTrue(User.objects.get(pk=self.super.pk).is_active)


# ---------------------------------------------------------------------------------------------
# Super admins
# ---------------------------------------------------------------------------------------------


class SuperUsersTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.other = make_super("super2@efind.test", name="Segundo Super")

    def form(self, **overrides):
        data = {"name": "Novo Super", "email": "Novo.Super@Efind.test ", "phone": "", "password": ""}
        data.update(overrides)
        return data

    def test_list_shows_only_super_admins(self):
        response = self.client.get(url("users"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({u.email for u in response.context["accounts"]}, {"super@efind.test", "super2@efind.test"})
        self.assertContains(response, "Segundo Super")
        self.assertContains(response, "Você")
        self.assertNotContains(response, "admin@a.test")

    def test_create_super_admin(self):
        response = self.client.post(url("user_create"), self.form())
        self.assertEqual(response.status_code, 200)
        creds = response.context["creds"]
        user = User.objects.get(email="novo.super@efind.test")
        self.assertEqual((user.role, user.campaign_id), (Role.SUPER_ADMIN, None))
        self.assertContains(response, creds.password)
        self.assertTrue(Client().login(username="novo.super@efind.test", password=creds.password))
        self.assertNotContains(self.client.get(url("users")), creds.password)
        self.assertTrue(AuditLog.objects.filter(action="user.create", entity_id=str(user.pk), campaign__isnull=True).exists())

    def test_create_with_duplicate_email_or_weak_password(self):
        response = self.client.post(url("user_create"), self.form(email="ADMIN@a.test"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["open_form"])
        self.assertContains(response, "Este e-mail já está cadastrado")
        response = self.client.post(url("user_create"), self.form(password="fraca"))
        self.assertIn("password", response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="novo.super@efind.test").exists())

    def test_deactivate_and_activate_another_super_admin(self):
        self.client.post(url("user_deactivate", self.other.pk))
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_active)
        self.assertFalse(Client().login(username="super2@efind.test", password=PASSWORD))
        self.client.post(url("user_activate", self.other.pk))
        self.other.refresh_from_db()
        self.assertTrue(self.other.is_active)

    def test_cannot_deactivate_yourself(self):
        response = self.client.post(url("user_deactivate", self.super.pk))
        self.assertTrue(any("própria conta" in m for m in msgs(response)))
        self.super.refresh_from_db()
        self.assertTrue(self.super.is_active)

    def test_deactivated_super_admin_loses_access_immediately(self):
        other_client = client_for(self.other)
        self.assertEqual(other_client.get(url("home")).status_code, 200)
        self.client.post(url("user_deactivate", self.other.pk))
        response = other_client.get(url("home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_reset_password_of_another_super_admin(self):
        response = self.client.post(url("user_reset_password", self.other.pk))
        self.assertEqual(response.status_code, 200)
        creds = response.context["creds"]
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_password(creds.password))
        self.assertContains(response, creds.password)

    def test_cannot_reset_own_password_here(self):
        old = User.objects.get(pk=self.super.pk).password
        response = self.client.post(url("user_reset_password", self.super.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("Meu perfil" in m for m in msgs(response)))
        self.assertEqual(User.objects.get(pk=self.super.pk).password, old)

    def test_campaign_users_are_404_on_super_user_routes(self):
        for name in ("user_reset_password", "user_deactivate", "user_activate"):
            self.assertEqual(self.client.post(url(name, self.admin_a.pk)).status_code, 404, name)
        self.assertTrue(User.objects.get(pk=self.admin_a.pk).is_active)

    def test_platform_keeps_at_least_one_active_super_admin(self):
        self.client.post(url("user_deactivate", self.other.pk))
        # o único super admin ativo restante é quem está logado: nem ele nem ninguém pode zerar os acessos
        response = self.client.post(url("user_deactivate", self.super.pk))
        self.assertEqual(User.objects.filter(role=Role.SUPER_ADMIN, is_active=True).count(), 1)
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------------------------


class AuditViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        audit("campaign.update", user=self.super, campaign=self.a, entity="Campaign", entity_id=self.a.pk, details={"fields": ["city"]}, ip="10.0.0.1")
        audit("user.create", user=self.admin_b, campaign=self.b, entity="User", entity_id=self.admin_b.pk, details={"role": "ADMIN"})
        audit("auth.login", user=self.super, campaign_id=None, ip="10.0.0.2")
        now = timezone.now()
        for seconds, action in ((3, "campaign.update"), (2, "user.create"), (1, "auth.login")):
            AuditLog.objects.filter(action=action).update(created_at=now - dt.timedelta(seconds=seconds))

    def rows(self, **params):
        response = self.client.get(url("audit"), params)
        self.assertEqual(response.status_code, 200)
        return response, response.context["rows"]

    def test_lists_everything_newest_first(self):
        response, rows = self.rows()
        self.assertEqual([r.action for r in rows], ["auth.login", "user.create", "campaign.update"])
        self.assertEqual(rows[2].action_label, "Campanha atualizada")
        for text in ("Campanha atualizada", "Usuário criado", "Login", "10.0.0.1", "Alfa Urna", "Plataforma", "Super Dono", "Ver detalhes"):
            self.assertContains(response, text)
        self.assertContains(response, "&quot;fields&quot;")  # JSON formatado e escapado

    def test_filter_by_campaign_action_and_platform(self):
        self.assertEqual([r.action for r in self.rows(campaign=str(self.a.pk))[1]], ["campaign.update"])
        self.assertEqual([r.action for r in self.rows(campaign="plataforma")[1]], ["auth.login"])
        self.assertEqual([r.action for r in self.rows(action="user.create")[1]], ["user.create"])
        self.assertEqual([r.action for r in self.rows(campaign=str(self.a.pk), action="user.create")[1]], [])
        response, rows = self.rows(campaign=str(self.a.pk), action="user.create")
        self.assertContains(response, "Nenhum registro encontrado")

    def test_filter_by_period_uses_sao_paulo_days(self):
        old = AuditLog.objects.get(action="campaign.update")
        AuditLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
        today = timezone.localdate()
        old_day = timezone.localtime(AuditLog.objects.get(pk=old.pk).created_at).date()
        self.assertEqual([r.action for r in self.rows(start=today.isoformat())[1]], ["auth.login", "user.create"])
        self.assertEqual([r.action for r in self.rows(end=old_day.isoformat())[1]], ["campaign.update"])
        both = self.rows(start=old_day.isoformat(), end=old_day.isoformat())[1]
        self.assertEqual([r.action for r in both], ["campaign.update"])
        self.assertEqual(len(self.rows(start=today.isoformat(), end=old_day.isoformat())[1]), 3)  # datas invertidas são trocadas

    def test_invalid_filters_are_ignored(self):
        response, rows = self.rows(campaign="lixo", action="hack.it", start="ontem")
        self.assertEqual(len(rows), 3)

    def test_pagination_is_50(self):
        AuditLog.objects.all().delete()
        AuditLog.objects.bulk_create([AuditLog(action="auth.login", campaign=self.a, ip="10.0.0.3") for _ in range(60)])
        first = self.client.get(url("audit"))
        self.assertEqual(len(first.context["rows"]), 50)
        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(self.client.get(url("audit"), {"page": 2}).context["rows"]), 10)

    def test_voter_events_never_expose_personal_data(self):
        audit(
            "voter.update",
            user=self.cabo_a,
            campaign=self.a,
            entity="Voter",
            entity_id=self.v1.pk,
            details={"name": self.v1.name, "phone": self.v1.phone, "email": "eleitora@exemplo.com", "contato": "eleitora@exemplo.com", "count": 7},
        )
        audit("voter.export", user=self.cabo_a, campaign=self.a, entity="Voter", details={"count": 12})
        response = self.client.get(url("audit"))
        self.assertContains(response, "Eleitor atualizado")
        self.assertContains(response, "Eleitores exportados")
        for secret in ("Eleitora Sigilosa", "5511900000", "eleitora@exemplo.com", "(11) 90000"):
            self.assertNotContains(response, secret)
        self.assertContains(response, "&quot;count&quot;: 7")

    def test_deleted_campaign_events_stay_visible_without_campaign(self):
        self.client.post(url("campaign_delete", self.b.pk), {"confirm_slug": "beta"})
        response, rows = self.rows(campaign="plataforma", action="campaign.delete")
        self.assertEqual(len(rows), 1)
        self.assertContains(response, "Campanha excluída")
        self.assertContains(response, "beta")

    def test_audit_page_is_efficient(self):
        AuditLog.objects.bulk_create([AuditLog(action="auth.login", campaign=self.a, user=self.cabo_a) for _ in range(5)])
        with CaptureQueriesContext(connection) as small:
            self.client.get(url("audit"))
        AuditLog.objects.bulk_create([AuditLog(action="auth.login", campaign=self.b, user=self.admin_b) for _ in range(40)])
        with CaptureQueriesContext(connection) as large:
            self.client.get(url("audit"))
        self.assertEqual(len(small), len(large))


# ---------------------------------------------------------------------------------------------
# Privacidade
# ---------------------------------------------------------------------------------------------


class PrivacyTests(BaseCase):
    SECRETS = ("Eleitora Sigilosa", "5511900000", "(11) 90000")

    def test_no_super_page_exposes_voter_personal_data(self):
        audit("voter.create", user=self.cabo_a, campaign=self.a, entity="Voter", entity_id=self.v1.pk, details={"name": self.v1.name, "phone": self.v1.phone})
        pages = [
            url("home"),
            url("campaigns"),
            url("campaign_detail", self.a.pk),
            url("campaign_detail", self.b.pk),
            url("users"),
            url("audit"),
            url("audit") + f"?campaign={self.a.pk}",
        ]
        for page in pages:
            response = self.client.get(page)
            self.assertEqual(response.status_code, 200, page)
            for secret in self.SECRETS:
                self.assertNotContains(response, secret, msg_prefix=page)

    def test_super_module_never_queries_voter_rows(self):
        """Eleitores só entram como contagens: nenhuma consulta das páginas seleciona colunas pessoais."""
        pages = [url("home"), url("campaigns"), url("campaign_detail", self.a.pk), url("audit")]
        with CaptureQueriesContext(connection) as ctx:
            for page in pages:
                self.client.get(page)
        for query in ctx.captured_queries:
            sql = query["sql"].lower()
            if 'from "voters_voter"' in sql:
                self.assertNotIn('"voters_voter"."name"', sql)
                self.assertNotIn('"voters_voter"."phone"', sql)
                self.assertNotIn('"voters_voter"."email"', sql)
                self.assertTrue("count(" in sql, sql)

    def test_campaign_admin_cannot_see_other_campaigns_via_super_routes(self):
        client = client_for(self.admin_a)
        response = client.get(url("campaign_detail", self.b.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/painel/")
