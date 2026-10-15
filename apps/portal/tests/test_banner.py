"""Banner do topo do formulário público (upload, validação, auditoria, página pública) e nome de urna opcional."""

from django.test import SimpleTestCase, TestCase

from apps.campaigns.models import Campaign
from apps.core.utils import display_name_fallback
from apps.portal import settings_rules as sr
from apps.portal.forms import IdentityForm
from apps.superadmin.forms import CampaignForm
from apps.superadmin.tests.helpers import campaign_post_data
from apps.voters.public import brand_for
from apps.voters.utils import safe_banner_url

from .helpers import data_url, identity_payload, jpeg_bytes, login, png_bytes, webp_bytes
from .test_settings_views import URL, SettingsBase


class BannerRulesTests(SimpleTestCase):
    def test_accepts_the_recommended_size_in_every_format(self):
        for raw, mime in ((png_bytes(2000, 800), "image/png"), (jpeg_bytes(2000, 800), "image/jpeg"), (webp_bytes(2000, 800), "image/webp")):
            self.assertEqual(sr.check_banner_data_url(data_url(raw, mime))[0], mime)

    def test_rejects_too_big_files_wrong_types_and_huge_dimensions(self):
        too_big = png_bytes(2000, 800) + b"\x00" * sr.BANNER_MAX_BYTES
        with self.assertRaisesMessage(sr.LogoError, "400 KB"):
            sr.check_banner_data_url(data_url(too_big))
        for bad in ("", "javascript:alert(1)", "https://exemplo.com/b.png", "data:image/svg+xml;base64,PHN2Zz4=",
                    "data:image/gif;base64,R0lGODlhAQABAAAAACw="):
            with self.assertRaises(sr.LogoError):
                sr.check_banner_data_url(bad)
        with self.assertRaisesMessage(sr.LogoError, "grandes demais"):
            sr.check_banner_data_url(data_url(png_bytes(sr.BANNER_MAX_SERVER_WIDTH + 1, 100)))

    def test_safe_urls(self):
        good = data_url(png_bytes(2000, 800))
        self.assertTrue(sr.is_safe_banner_url(good))
        self.assertEqual(safe_banner_url(good), good)
        for bad in ("", None, "javascript:alert(1)", "https://exemplo.com/b.png", "/static/x.png", "data:image/svg+xml;base64,PHN2Zz4=",
                    "data:image/png;base64,AAA\"onerror=\"x"):
            self.assertFalse(sr.is_safe_banner_url(bad), bad)
            self.assertEqual(safe_banner_url(bad), "", bad)


class BallotNameOptionalTests(SimpleTestCase):
    def test_fallback_is_the_candidate_name_cut_on_a_word(self):
        self.assertEqual(display_name_fallback("  Maria   Souza "), "Maria Souza")
        long_name = "Maria Aparecida de Souza Albuquerque Montenegro Vasconcelos Ferreira da Silva"
        short = display_name_fallback(long_name, 60)
        self.assertLessEqual(len(short), 60)
        self.assertTrue(long_name.startswith(short))
        self.assertFalse(short.endswith(" "))
        self.assertEqual(display_name_fallback(None), "")

    def test_identity_form_accepts_blank_ballot_name_and_uses_the_candidate_name(self):
        form = IdentityForm(identity_payload(ballot_name=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["ballot_name"], "Maria Aparecida Souza")
        self.assertFalse(form.fields["ballot_name"].required)

    def test_one_letter_ballot_name_is_still_rejected(self):
        form = IdentityForm(identity_payload(ballot_name="M"))
        self.assertFalse(form.is_valid())
        self.assertIn("ballot_name", form.errors)

    def test_super_admin_campaign_form_accepts_blank_ballot_name(self):
        data = {k: v for k, v in campaign_post_data(ballot_name="").items() if not k.startswith("admin-")}
        form = CampaignForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["ballot_name"], "João da Silva")


class BannerFormTests(SimpleTestCase):
    def test_replace_needs_a_valid_banner_and_other_actions_ignore_the_data(self):
        ok = IdentityForm(identity_payload(banner_action="replace", banner_data=data_url(png_bytes(2000, 800))))
        self.assertTrue(ok.is_valid(), ok.errors)
        bad = IdentityForm(identity_payload(banner_action="replace", banner_data=""))
        self.assertFalse(bad.is_valid())
        self.assertIn("banner_data", bad.errors)
        ignored = IdentityForm(identity_payload(banner_action="keep", banner_data=data_url(png_bytes(2000, 800))))
        self.assertTrue(ignored.is_valid(), ignored.errors)
        self.assertEqual(ignored.cleaned_data["banner_data"], "")

    def test_oversized_banner_is_rejected_with_the_banner_limit(self):
        big = data_url(png_bytes(2000, 800) + b"\x00" * (500 * 1024))
        form = IdentityForm(identity_payload(banner_action="replace", banner_data=big))
        self.assertFalse(form.is_valid())
        self.assertIn("400 KB", form.errors["banner_data"][0])


class BannerViewTests(SettingsBase):
    def setUp(self):
        self.client = login("admin@a.com")

    def test_replace_saves_audits_only_the_field_name_and_renders_in_settings(self):
        url = data_url(png_bytes(2000, 800))
        response = self.client.post(URL, identity_payload(banner_action="replace", banner_data=url))
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.banner_url, url)
        details = self.audits().get().details
        self.assertIn("banner_url", details["fields"])
        self.assertNotIn(url[:60], str(details))  # a imagem nunca vai para a auditoria
        page = self.client.get(URL)
        self.assertContains(page, 'id="portal-banner-state"')
        self.assertContains(page, "2000 × 800 px")
        self.assertContains(page, "Enviar banner")

    def test_logo_and_banner_are_independent(self):
        logo, banner = data_url(png_bytes(16, 16)), data_url(png_bytes(2000, 800))
        self.client.post(URL, identity_payload(logo_action="replace", logo_data=logo, banner_action="replace", banner_data=banner))
        self.client.post(URL, identity_payload(banner_action="remove"))  # remove o banner e mantém o logo
        self.campaign.refresh_from_db()
        self.assertEqual((self.campaign.logo_url, self.campaign.banner_url), (logo, ""))

    def test_invalid_banner_changes_nothing_and_shows_the_error(self):
        response = self.client.post(URL, identity_payload(banner_action="replace", banner_data="javascript:alert(1)", ballot_name="Outra"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("banner_data", response.context["identity_form"].errors)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.banner_url, "")
        self.assertNotEqual(self.campaign.ballot_name, "Outra")

    def test_failed_save_keeps_the_new_banner_for_resubmission(self):
        url = data_url(png_bytes(2000, 800))
        response = self.client.post(URL, identity_payload(banner_action="replace", banner_data=url, primary_color="x"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["banner_state"], {"saved": "", "action": "replace", "echo": url})

    def test_blank_ballot_name_is_saved_as_the_candidate_name(self):
        response = self.client.post(URL, identity_payload(ballot_name=""))
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.ballot_name, "Maria Aparecida Souza")

    def test_only_admins_with_edit_permission_can_send_a_banner(self):
        response = login("cabo@a.com").post(URL, identity_payload(banner_action="replace", banner_data=data_url(png_bytes(2000, 800))))
        self.assertEqual(response.status_code, 403)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.banner_url, "")


class PublicBannerTests(SettingsBase):
    def page(self):
        return self.client.get(f"/c/{self.admin.invite_code}/")

    def test_public_form_shows_the_banner_instead_of_logo_and_name(self):
        banner = data_url(png_bytes(2000, 800))
        Campaign.objects.filter(pk=self.campaign.pk).update(banner_url=banner, logo_url=data_url(png_bytes(16, 16)))
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, banner)
        self.assertContains(response, "Banner de Alfa")
        self.assertNotContains(response, "Logo de Alfa")

    def test_without_banner_the_header_keeps_logo_and_name(self):
        Campaign.objects.filter(pk=self.campaign.pk).update(banner_url="", logo_url=data_url(png_bytes(16, 16)))
        response = self.page()
        self.assertContains(response, "Logo de Alfa")
        self.assertNotContains(response, "Banner de Alfa")

    def test_unsafe_banner_is_never_rendered(self):
        Campaign.objects.filter(pk=self.campaign.pk).update(banner_url='javascript:alert(1)"onerror="x')
        response = self.page()
        self.assertNotContains(response, "javascript:alert")
        self.assertNotContains(response, "Banner de Alfa")
        self.assertEqual(brand_for(Campaign.objects.get(pk=self.campaign.pk)).banner_url, "")
