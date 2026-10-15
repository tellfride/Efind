"""Serviços de escrita do super admin: criação com bootstrap, exclusão, status e contas."""

from unittest.mock import patch

from django.contrib.sessions.models import Session
from django.test import TestCase

from apps.accounts.models import RolePermission, User
from apps.auditlog.models import AuditLog
from apps.campaigns.models import Campaign
from apps.core.constants import BroadcastStatus, CampaignStatus, Role
from apps.dashboards.models import Dashboard
from apps.messaging.models import Broadcast
from apps.superadmin import services
from apps.superadmin.services import EmailAlreadyUsed, ServiceError
from apps.voters.models import Voter

from .helpers import fast_hasher, make_campaign, make_super, make_user, make_voter, request_for


def campaign_data(**overrides):
    data = {
        "candidate_name": "João da Silva",
        "ballot_name": "João Silva",
        "ballot_number": "12345",
        "party": "PSD",
        "office": "VEREADOR",
        "city": "Campinas",
        "state": "SP",
        "election_year": 2026,
        "primary_color": "#112233",
        "voter_goal": 100,
    }
    data.update(overrides)
    return data


def admin_data(**overrides):
    data = {"name": "Maria Admin", "email": "maria@exemplo.com", "phone": "5519987654321", "password": ""}
    data.update(overrides)
    return data


@fast_hasher
class CreateCampaignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.super = make_super()
        cls.request = request_for(cls.super)

    def create(self, **overrides):
        return services.create_campaign_with_admin(
            self.request, campaign_data=campaign_data(**overrides.pop("campaign", {})), admin_data=admin_data(**overrides)
        )

    def test_creates_campaign_admin_permissions_and_dashboards(self):
        campaign, admin, creds = self.create()
        self.assertEqual(campaign.slug, "joao-silva")
        self.assertEqual(campaign.status, CampaignStatus.ACTIVE)
        # bootstrap_campaign: permissões padrão de COORDENADOR e CABO + dashboards-modelo
        self.assertTrue(RolePermission.objects.filter(campaign=campaign, role=Role.COORDENADOR).exists())
        self.assertTrue(RolePermission.objects.filter(campaign=campaign, role=Role.CABO).exists())
        self.assertTrue(Dashboard.objects.filter(campaign=campaign).exists())
        # primeiro administrador
        self.assertEqual((admin.role, admin.campaign_id, admin.email), (Role.ADMIN, campaign.pk, "maria@exemplo.com"))
        self.assertTrue(admin.invite_code)
        self.assertTrue(admin.is_active)
        self.assertEqual(admin.phone, "5519987654321")

    def test_generated_password_is_returned_and_hashed(self):
        _campaign, admin, creds = self.create()
        self.assertTrue(creds.generated)
        self.assertRegex(creds.password, r"^[A-Za-z]{8}[0-9]{2}$")
        self.assertTrue(admin.check_password(creds.password))
        self.assertNotEqual(admin.password, creds.password)
        self.assertTrue(creds.login_url.endswith("/login/"))

    def test_explicit_password_is_used(self):
        _campaign, admin, creds = self.create(password="Minha#Senha2026")
        self.assertFalse(creds.generated)
        self.assertEqual(creds.password, "Minha#Senha2026")
        self.assertTrue(admin.check_password("Minha#Senha2026"))

    def test_slug_is_unique_for_same_ballot_name(self):
        slugs = [self.create(email=f"adm{i}@exemplo.com")[0].slug for i in range(3)]
        self.assertEqual(slugs, ["joao-silva", "joao-silva-2", "joao-silva-3"])

    def test_audits_campaign_and_user_creation_without_secrets(self):
        campaign, admin, creds = self.create()
        logs = AuditLog.objects.filter(campaign=campaign)
        self.assertEqual({log.action for log in logs}, {"campaign.create", "user.create"})
        for log in logs:
            self.assertEqual(log.user_id, self.super.pk)
            blob = str(log.details)
            self.assertNotIn(creds.password, blob)
            self.assertNotIn("maria@exemplo.com", blob)
            self.assertNotIn("Maria", blob)
        self.assertEqual(logs.get(action="user.create").entity_id, str(admin.pk))
        self.assertEqual(logs.get(action="campaign.create").details["slug"], "joao-silva")

    def test_duplicate_email_rolls_everything_back(self):
        other = make_campaign("beta")
        make_user(other, "maria@exemplo.com", Role.ADMIN)
        before = (Campaign.objects.count(), User.objects.count(), RolePermission.objects.count(), Dashboard.objects.count(), AuditLog.objects.count())
        with self.assertRaises(EmailAlreadyUsed):
            self.create()
        after = (Campaign.objects.count(), User.objects.count(), RolePermission.objects.count(), Dashboard.objects.count(), AuditLog.objects.count())
        self.assertEqual(before, after)

    def test_email_clash_is_case_insensitive_at_service_level(self):
        other = make_campaign("beta")
        make_user(other, "maria@exemplo.com", Role.ADMIN)
        with self.assertRaises(EmailAlreadyUsed):
            self.create(email="maria@exemplo.com")
        self.assertFalse(Campaign.objects.filter(slug="joao-silva").exists())


@fast_hasher
class DeleteCampaignTests(TestCase):
    def setUp(self):
        self.super = make_super()
        self.request = request_for(self.super)
        self.a = make_campaign("alfa", ballot_name="Alfa Urna")
        self.b = make_campaign("beta")
        self.admin_a = make_user(self.a, "admin@a.test", Role.ADMIN)
        self.coord_a = make_user(self.a, "coord@a.test", Role.COORDENADOR, parent=self.admin_a)
        self.cabo_a = make_user(self.a, "cabo@a.test", Role.CABO, parent=self.coord_a)
        self.admin_b = make_user(self.b, "admin@b.test", Role.ADMIN)
        for n, owner in enumerate([self.admin_a, self.coord_a, self.cabo_a, self.cabo_a], start=1):
            make_voter(self.a, owner, n)
        make_voter(self.b, self.admin_b, 50)

    def test_deletes_campaign_with_voters_registered_by_its_team(self):
        # Voter.registered_by é RESTRICT: sem apagar os apoiadores antes, a exclusão em cascata falharia
        pk = self.a.pk
        services.delete_campaign(self.request, self.a)
        self.assertFalse(Campaign.objects.filter(pk=pk).exists())
        self.assertFalse(Voter.objects.filter(campaign_id=pk).exists())
        self.assertFalse(User.objects.filter(campaign_id=pk).exists())
        self.assertFalse(RolePermission.objects.filter(campaign_id=pk).exists())
        self.assertFalse(Dashboard.objects.filter(campaign_id=pk).exists())

    def test_voters_are_deleted_in_batches(self):
        with patch.object(services, "VOTER_DELETE_CHUNK", 1):  # 4 apoiadores → 4 lotes
            services.delete_campaign(self.request, self.a)
        self.assertFalse(Voter.objects.filter(campaign_id=self.a.pk).exists())
        self.assertEqual(Voter.objects.count(), 1)  # o apoiador da outra campanha continua

    def test_other_campaigns_and_super_admins_are_untouched(self):
        services.delete_campaign(self.request, self.a)
        self.assertTrue(Campaign.objects.filter(pk=self.b.pk).exists())
        self.assertEqual(Voter.objects.filter(campaign=self.b).count(), 1)
        self.assertTrue(User.objects.filter(pk=self.admin_b.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.super.pk).exists())

    def test_deletion_is_audited_without_campaign(self):
        AuditLog.objects.create(action="voter.create", campaign=self.a)  # some junto com a campanha
        pk = self.a.pk
        services.delete_campaign(self.request, self.a)
        self.assertFalse(AuditLog.objects.filter(campaign_id=pk).exists())
        log = AuditLog.objects.get(action="campaign.delete")
        self.assertIsNone(log.campaign_id)
        self.assertEqual(log.user_id, self.super.pk)
        self.assertEqual(log.entity_id, str(pk))
        self.assertEqual(log.details, {"slug": "alfa", "ballot_name": "Alfa Urna"})

    def test_failure_rolls_back_voter_deletion(self):
        voters_before = Voter.objects.filter(campaign=self.a).count()
        original = Campaign.delete

        def boom(self, *args, **kwargs):
            raise services.RestrictedError("bloqueado", set())

        Campaign.delete = boom
        try:
            with self.assertRaises(ServiceError):
                services.delete_campaign(self.request, self.a)
        finally:
            Campaign.delete = original
        self.assertEqual(Voter.objects.filter(campaign=self.a).count(), voters_before)
        self.assertTrue(Campaign.objects.filter(pk=self.a.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action="campaign.delete").exists())


@fast_hasher
class CampaignStatusTests(TestCase):
    def setUp(self):
        self.super = make_super()
        self.request = request_for(self.super)
        self.campaign = make_campaign("alfa")

    def test_suspend_and_reactivate_are_audited_and_idempotent(self):
        self.assertEqual(services.set_campaign_status(self.request, self.campaign, suspend=True), 0)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, CampaignStatus.SUSPENDED)
        self.assertIsNone(services.set_campaign_status(self.request, self.campaign, suspend=True))
        services.set_campaign_status(self.request, self.campaign, suspend=False)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, CampaignStatus.ACTIVE)
        self.assertIsNone(services.set_campaign_status(self.request, self.campaign, suspend=False))
        actions = list(AuditLog.objects.filter(campaign=self.campaign).order_by("created_at").values_list("action", flat=True))
        self.assertEqual(actions, ["campaign.suspend", "campaign.activate"])

    def test_suspending_pauses_running_broadcasts_only(self):
        running = Broadcast.objects.create(campaign=self.campaign, name="A", status=BroadcastStatus.RUNNING)
        done = Broadcast.objects.create(campaign=self.campaign, name="B", status=BroadcastStatus.COMPLETED)
        other = make_campaign("beta")
        other_running = Broadcast.objects.create(campaign=other, name="C", status=BroadcastStatus.RUNNING)
        self.assertEqual(services.set_campaign_status(self.request, self.campaign, suspend=True), 1)
        for broadcast, expected in ((running, BroadcastStatus.PAUSED), (done, BroadcastStatus.COMPLETED), (other_running, BroadcastStatus.RUNNING)):
            broadcast.refresh_from_db()
            self.assertEqual(broadcast.status, expected)


@fast_hasher
class AccountTests(TestCase):
    def setUp(self):
        self.super = make_super("super1@efind.test")
        self.request = request_for(self.super)
        self.campaign = make_campaign("alfa")

    def test_create_super_admin_has_no_campaign(self):
        user, creds = services.create_account(self.request, role=Role.SUPER_ADMIN, campaign=None, data=admin_data(email="novo@efind.test"))
        self.assertEqual((user.role, user.campaign_id), (Role.SUPER_ADMIN, None))
        self.assertTrue(user.check_password(creds.password))
        log = AuditLog.objects.get(action="user.create")
        self.assertIsNone(log.campaign_id)
        self.assertNotIn(creds.password, str(log.details))

    def test_create_account_with_duplicate_email(self):
        with self.assertRaises(EmailAlreadyUsed):
            services.create_account(self.request, role=Role.SUPER_ADMIN, campaign=None, data=admin_data(email="SUPER1@efind.test"))
        self.assertEqual(User.objects.filter(role=Role.SUPER_ADMIN).count(), 1)

    def test_reset_password_changes_hash_and_invalidates_sessions(self):
        admin = make_user(self.campaign, "admin@a.test", Role.ADMIN)
        old_hash = admin.password
        from django.test import Client

        client = Client()
        client.force_login(admin)
        self.assertEqual(Session.objects.count(), 1)
        creds = services.reset_password(self.request, admin, campaign=self.campaign)
        admin.refresh_from_db()
        self.assertNotEqual(admin.password, old_hash)
        self.assertTrue(admin.check_password(creds.password))
        self.assertFalse(admin.check_password("Senha@12345"))
        self.assertTrue(creds.generated)
        log = AuditLog.objects.get(action="user.password_reset")
        self.assertEqual(log.campaign_id, self.campaign.pk)
        self.assertNotIn(creds.password, str(log.details))
        # a sessão antiga deixa de valer (hash de autenticação mudou)
        response = client.get("/painel/perfil/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_cannot_deactivate_self(self):
        other = make_super("super2@efind.test")
        with self.assertRaises(ServiceError):
            services.set_user_active(request_for(other), other, active=False)
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_super_admin_can_deactivate_another_while_one_stays_active(self):
        other = make_super("super2@efind.test")
        self.assertTrue(services.set_user_active(self.request, other, active=False))
        other.refresh_from_db()
        self.assertFalse(other.is_active)
        self.assertEqual(AuditLog.objects.filter(action="user.deactivate").count(), 1)
        self.assertFalse(services.set_user_active(self.request, other, active=False))  # já estava desativado
        self.assertTrue(services.set_user_active(self.request, other, active=True))
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_last_active_super_admin_is_protected(self):
        # ator "velho" (já desativado em outra aba) tentando desativar o último super admin ativo
        stale = make_super("stale@efind.test", is_active=False)
        with self.assertRaises(ServiceError) as ctx:
            services.set_user_active(request_for(stale), self.super, active=False)
        self.assertIn("pelo menos um super admin ativo", str(ctx.exception))
        self.super.refresh_from_db()
        self.assertTrue(self.super.is_active)

    def test_last_active_campaign_admin_is_protected(self):
        only_admin = make_user(self.campaign, "admin@a.test", Role.ADMIN)
        with self.assertRaises(ServiceError) as ctx:
            services.set_user_active(self.request, only_admin, active=False, campaign=self.campaign)
        self.assertIn("pelo menos um administrador ativo", str(ctx.exception))
        second = make_user(self.campaign, "admin2@a.test", Role.ADMIN)
        self.assertTrue(services.set_user_active(self.request, second, active=False, campaign=self.campaign))
        with self.assertRaises(ServiceError):
            services.set_user_active(self.request, only_admin, active=False, campaign=self.campaign)

    def test_admin_of_another_campaign_does_not_count_as_peer(self):
        only_admin = make_user(self.campaign, "admin@a.test", Role.ADMIN)
        other = make_campaign("beta")
        make_user(other, "admin@b.test", Role.ADMIN)
        with self.assertRaises(ServiceError):
            services.set_user_active(self.request, only_admin, active=False, campaign=self.campaign)
