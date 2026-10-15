"""Lógica pura (sem banco) e formulários do super admin."""

import datetime as dt

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.core.constants import Role
from apps.superadmin import selectors
from apps.superadmin.forms import (
    PLATFORM_SCOPE,
    AccountForm,
    AuditFilterForm,
    CampaignForm,
    CampaignListForm,
    DeleteCampaignForm,
    expected_ballot_number_length,
)
from apps.superadmin.services import (
    IssuedCredentials,
    campaign_slug_base,
    generate_temp_password,
    unique_slug,
)

from .helpers import campaign_post_data, fast_hasher, make_campaign, make_user


class PasswordAndSlugTests(SimpleTestCase):
    def test_temp_password_is_8_letters_plus_2_digits(self):
        for _ in range(50):
            password = generate_temp_password()
            self.assertRegex(password, r"^[A-Za-z]{8}[0-9]{2}$")

    def test_temp_passwords_are_not_repeated(self):
        self.assertEqual(len({generate_temp_password() for _ in range(200)}), 200)

    def test_slug_base_from_ballot_name(self):
        self.assertEqual(campaign_slug_base("João da Silva"), "joao-da-silva")
        self.assertEqual(campaign_slug_base("  Dra. Ana  Paula!! "), "dra-ana-paula")

    def test_slug_base_fallback_and_length(self):
        self.assertEqual(campaign_slug_base("!!!"), "campanha")
        self.assertEqual(campaign_slug_base(""), "campanha")
        # sobra espaço para o sufixo "-99999" dentro dos 80 caracteres do campo
        self.assertLessEqual(len(campaign_slug_base("a" * 200)), 54)

    def test_unique_slug_sequence(self):
        self.assertEqual(unique_slug("maria", []), "maria")
        self.assertEqual(unique_slug("maria", ["outra"]), "maria")
        self.assertEqual(unique_slug("maria", ["maria"]), "maria-2")
        self.assertEqual(unique_slug("maria", ["maria", "maria-2"]), "maria-3")
        self.assertEqual(unique_slug("maria", ["maria", "maria-3"]), "maria-2")  # primeiro livre da sequência
        self.assertEqual(unique_slug("maria", iter(["maria", "maria-2", "maria-3"])), "maria-4")

    def test_credentials_copy_text(self):
        creds = IssuedCredentials(name="Ana", email="ana@x.com", password="Abcdefgh12", generated=True, login_url="https://e.com/login/")
        self.assertEqual(creds.password_label, "Senha provisória")
        for expected in ("https://e.com/login/", "ana@x.com", "Abcdefgh12"):
            self.assertIn(expected, creds.copy_all)
        self.assertEqual(IssuedCredentials("A", "a@x.com", "p", False, "u").password_label, "Senha")

    def test_ballot_number_length_by_office(self):
        self.assertEqual(expected_ballot_number_length("VEREADOR"), 5)
        self.assertEqual(expected_ballot_number_length("DEPUTADO_FEDERAL"), 4)
        self.assertEqual(expected_ballot_number_length("SENADOR"), 3)
        self.assertEqual(expected_ballot_number_length("PREFEITO"), 2)
        self.assertIsNone(expected_ballot_number_length("OUTRO"))


class AuditSanitizeTests(SimpleTestCase):
    def test_voter_events_mask_personal_fields(self):
        details = {"name": "Maria Silva", "phone": "5511987654321", "count": 3, "nested": {"email": "a@b.com", "ok": "sim"}}
        clean = selectors.sanitize_audit_details("voter.update", "Voter", details)
        self.assertEqual(clean["name"], selectors.REDACTED)
        self.assertEqual(clean["phone"], selectors.REDACTED)
        self.assertEqual(clean["nested"]["email"], selectors.REDACTED)
        self.assertEqual(clean["nested"]["ok"], "sim")
        self.assertEqual(clean["count"], 3)

    def test_voter_events_mask_personal_looking_values(self):
        clean = selectors.sanitize_audit_details("voter.export", "Voter", {"note": "ligar 11 98765-4321", "who": "ana@x.com", "n": "12"})
        self.assertEqual(clean["who"], selectors.REDACTED)
        self.assertEqual(clean["n"], "12")

    def test_other_events_are_kept(self):
        details = {"slug": "maria", "fields": ["city"]}
        self.assertEqual(selectors.sanitize_audit_details("campaign.update", "Campaign", details), details)
        self.assertIsNone(selectors.sanitize_audit_details("voter.update", "Voter", None))

    def test_entity_based_detection(self):
        self.assertTrue(selectors.is_voter_related("broadcast.start", "BroadcastMessage"))
        self.assertTrue(selectors.is_voter_related("voter.delete", ""))
        self.assertFalse(selectors.is_voter_related("campaign.create", "Campaign"))

    def test_pretty_details(self):
        self.assertEqual(selectors.pretty_details(None), "")
        self.assertEqual(selectors.pretty_details({}), "")
        self.assertIn('"a": 1', selectors.pretty_details({"a": 1}))
        self.assertTrue(selectors.pretty_details({"a": "x" * 5000}, limit=100).endswith("…"))


@fast_hasher
class CampaignFormTests(TestCase):
    def valid_data(self, **overrides):
        data = {k: v for k, v in campaign_post_data().items() if not k.startswith("admin-")}
        data.update(overrides)
        return data

    def test_valid_form(self):
        form = CampaignForm(self.valid_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["primary_color"], "#112233")
        self.assertEqual(form.cleaned_data["voter_goal"], 5000)

    def test_unbound_defaults(self):
        form = CampaignForm()
        self.assertEqual(form.initial["election_year"], timezone.localdate().year)
        self.assertEqual(form.initial["primary_color"], "#4f46e5")

    def test_required_fields(self):
        form = CampaignForm({})
        self.assertFalse(form.is_valid())
        for name in ("candidate_name", "office", "election_year"):
            self.assertIn(name, form.errors)

    def test_empty_color_uses_default_and_color_is_lowercased(self):
        form = CampaignForm(self.valid_data(primary_color=""))
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["primary_color"], "#4f46e5")
        form = CampaignForm(self.valid_data(primary_color="#AABBCC"))
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["primary_color"], "#aabbcc")

    def test_invalid_colors_are_rejected(self):
        for bad in ("red", "#12345", "#12345g", "112233", "#1122334", "javascript:alert(1)"):
            form = CampaignForm(self.valid_data(primary_color=bad))
            self.assertFalse(form.is_valid(), bad)
            self.assertIn("primary_color", form.errors)

    def test_ballot_number_rules(self):
        self.assertFalse(CampaignForm(self.valid_data(ballot_number="12")).is_valid())  # vereador = 5 dígitos
        self.assertFalse(CampaignForm(self.valid_data(ballot_number="12a45")).is_valid())
        self.assertTrue(CampaignForm(self.valid_data(ballot_number="")).is_valid())  # opcional
        self.assertTrue(CampaignForm(self.valid_data(office="PREFEITO", ballot_number="45")).is_valid())
        self.assertTrue(CampaignForm(self.valid_data(office="OUTRO", ballot_number="123")).is_valid())

    def test_state_year_and_goal_limits(self):
        self.assertFalse(CampaignForm(self.valid_data(state="XX")).is_valid())
        self.assertFalse(CampaignForm(self.valid_data(election_year="1900")).is_valid())
        self.assertFalse(CampaignForm(self.valid_data(voter_goal="0")).is_valid())
        self.assertFalse(CampaignForm(self.valid_data(voter_goal="abc")).is_valid())
        self.assertTrue(CampaignForm(self.valid_data(voter_goal="")).is_valid())

    def test_text_fields_are_trimmed(self):
        form = CampaignForm(self.valid_data(candidate_name="  Ana Souza  ", ballot_name="  Ana  ", party="  PT ", city=" Santos "))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["candidate_name"], "Ana Souza")
        self.assertEqual(form.cleaned_data["party"], "PT")
        self.assertEqual(form.cleaned_data["city"], "Santos")


@fast_hasher
class AccountFormTests(TestCase):
    def data(self, **overrides):
        data = {"name": "Maria Silva", "email": "  Maria@Exemplo.com ", "phone": "(19) 98765-4321", "password": ""}
        data.update(overrides)
        return data

    def test_email_is_trimmed_and_lowercased(self):
        form = AccountForm(self.data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "maria@exemplo.com")
        self.assertEqual(form.cleaned_data["phone"], "5519987654321")
        self.assertEqual(form.cleaned_data["password"], "")

    def test_email_must_be_globally_unique_case_insensitive(self):
        campaign = make_campaign("alfa")
        make_user(campaign, "maria@exemplo.com", Role.CABO)
        form = AccountForm(self.data(email="MARIA@exemplo.COM"))
        self.assertFalse(form.is_valid())
        self.assertIn("já está cadastrado", form.errors["email"][0])

    def test_phone_is_optional_but_validated(self):
        self.assertTrue(AccountForm(self.data(phone="")).is_valid())
        form = AccountForm(self.data(phone="123"))
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)

    def test_password_rules(self):
        self.assertTrue(AccountForm(self.data(password="Segredo2026x")).is_valid())
        for bad in ("abcdefghij", "1234567890", "ab12", "12345678"):
            form = AccountForm(self.data(password=bad))
            self.assertFalse(form.is_valid(), bad)
            self.assertIn("password", form.errors)

    def test_name_required(self):
        self.assertFalse(AccountForm(self.data(name="  ")).is_valid())
        self.assertFalse(AccountForm(self.data(name="Al")).is_valid())

    def test_prefixed_form(self):
        form = AccountForm({"admin-name": "Maria Silva", "admin-email": "m@x.com"}, prefix="admin")
        self.assertTrue(form.is_valid(), form.errors)


class OtherFormTests(TestCase):
    def test_delete_form_requires_exact_slug(self):
        campaign = make_campaign("alfa")
        self.assertTrue(DeleteCampaignForm({"confirm_slug": "alfa"}, campaign=campaign).is_valid())
        self.assertTrue(DeleteCampaignForm({"confirm_slug": " alfa "}, campaign=campaign).is_valid())
        for bad in ("", "ALFA", "alfa-2", "beta"):
            self.assertFalse(DeleteCampaignForm({"confirm_slug": bad}, campaign=campaign).is_valid(), bad)
        self.assertFalse(DeleteCampaignForm({"confirm_slug": "alfa"}).is_valid())  # sem campanha nunca valida

    def test_audit_filter_form_choices_and_swapped_dates(self):
        campaign = make_campaign("alfa", ballot_name="Alfa Urna")
        form = AuditFilterForm({"campaign": str(campaign.pk), "action": "campaign.create", "start": "2026-05-10", "end": "2026-05-01"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["start"], dt.date(2026, 5, 1))
        self.assertEqual(form.cleaned_data["end"], dt.date(2026, 5, 10))
        values = [value for value, _label in form.fields["campaign"].choices]
        self.assertIn(PLATFORM_SCOPE, values)
        self.assertIn(str(campaign.pk), values)
        self.assertIn("campaign.create", [value for value, _label in form.fields["action"].choices])

    def test_audit_filter_form_rejects_unknown_values(self):
        form = AuditFilterForm({"campaign": "nao-existe", "action": "hack.it", "start": "ontem"})
        self.assertFalse(form.is_valid())
        for name in ("campaign", "action", "start"):
            self.assertIn(name, form.errors)

    def test_campaign_list_form(self):
        self.assertTrue(CampaignListForm({"q": "ana", "status": "ACTIVE"}).is_valid())
        self.assertFalse(CampaignListForm({"status": "XYZ"}).is_valid())
