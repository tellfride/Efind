"""Configurações da campanha: acesso, edição (POST), auditoria das alterações e isolamento."""

from django.contrib.messages import get_messages
from django.test import Client, TestCase

from apps.accounts.models import User
from apps.auditlog.models import AuditLog
from apps.campaigns.models import Campaign

from .helpers import (
    PASSWORD,
    Role,
    data_url,
    fast_hashing,
    grant,
    identity_payload,
    jpeg_bytes,
    login,
    make_campaign,
    make_user,
    png_bytes,
    public_form_payload,
)

URL = "/painel/configuracoes/"


@fast_hashing
class SettingsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("alfa", city="Santos", state="SP")
        cls.other = make_campaign("beta")
        cls.admin = make_user(cls.campaign, "admin@a.com", Role.ADMIN)
        cls.coord = make_user(cls.campaign, "coord@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.cabo = make_user(cls.campaign, "cabo@a.com", Role.CABO, parent=cls.coord)
        cls.admin_b = make_user(cls.other, "admin@b.com", Role.ADMIN)
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD)

    def messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    def audits(self, action="settings.update"):
        return AuditLog.objects.filter(campaign=self.campaign, action=action)


class SettingsAccessTests(SettingsBase):
    def test_anonymous_is_redirected_to_login(self):
        response = Client().get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/?next="))

    def test_post_anonymous_is_redirected_and_changes_nothing(self):
        response = Client().post(URL, identity_payload(ballot_name="Invasor"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))
        self.campaign.refresh_from_db()
        self.assertNotEqual(self.campaign.ballot_name, "Invasor")

    def test_super_admin_is_sent_to_super_panel(self):
        self.assertEqual(login("super@x.com").get(URL).status_code, 302)

    def test_admin_page_renders_with_current_data(self):
        response = login("admin@a.com").get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Identidade da campanha")
        self.assertContains(response, "Formulário público de cadastro")
        self.assertContains(response, "Informações da campanha")
        self.assertContains(response, 'value="Santos"')
        self.assertContains(response, self.campaign.slug)
        self.assertContains(response, f"/c/{self.admin.invite_code}/")
        self.assertContains(response, "js/portal/settings.js")
        self.assertContains(response, 'id="portal-settings-config"')
        self.assertNotContains(response, "Somente leitura")
        self.assertContains(response, "Salvar identidade")

    def test_info_card_shows_election_year_without_thousand_separator(self):
        # Regressão (QA no navegador): com USE_THOUSAND_SEPARATOR o ano saía como "2.026"
        response = login("admin@a.com").get(URL)
        self.assertContains(response, "Vereador(a) · 2026</dd>")
        self.assertNotContains(response, "2.026")

    def test_page_shows_default_consent_as_placeholder(self):
        response = login("admin@a.com").get(URL)
        self.assertContains(response, "Autorizo a campanha de {{candidato}}")  # placeholder do textarea
        self.assertContains(response, "Restaurar texto padrão")

    def test_coordinator_and_cabo_forbidden_by_default(self):
        self.assertEqual(login("coord@a.com").get(URL).status_code, 403)
        self.assertEqual(login("cabo@a.com").get(URL).status_code, 403)
        self.assertEqual(login("coord@a.com").post(URL, identity_payload()).status_code, 403)

    def test_view_only_user_sees_read_only_page_and_cannot_post(self):
        grant(self.campaign, Role.COORDENADOR, "configuracoes", can_view=True)
        client = login("coord@a.com")
        response = client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Somente leitura")
        self.assertContains(response, "disabled")
        self.assertNotContains(response, "Salvar identidade")
        self.assertNotContains(response, "Salvar formulário")

        post = client.post(URL, identity_payload(ballot_name="Hackeado"))
        self.assertEqual(post.status_code, 403)
        post = client.post(URL, public_form_payload(form_title="Hackeado"))
        self.assertEqual(post.status_code, 403)
        self.campaign.refresh_from_db()
        self.assertNotEqual(self.campaign.ballot_name, "Hackeado")
        self.assertNotEqual(self.campaign.form_title, "Hackeado")
        self.assertEqual(self.audits().count(), 0)

    def test_user_with_edit_permission_can_save(self):
        grant(self.campaign, Role.COORDENADOR, "configuracoes", can_view=True, can_edit=True)
        response = login("coord@a.com").post(URL, identity_payload(ballot_name="Coord Editou"))
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.ballot_name, "Coord Editou")

    def test_edit_without_view_has_no_effect(self):
        grant(self.campaign, Role.COORDENADOR, "configuracoes", can_view=False, can_edit=True)
        self.assertEqual(login("coord@a.com").get(URL).status_code, 403)

    def test_csrf_is_enforced(self):
        client = login("admin@a.com", enforce_csrf_checks=True)
        response = client.post(URL, identity_payload(ballot_name="Sem CSRF"))
        self.assertEqual(response.status_code, 403)
        self.campaign.refresh_from_db()
        self.assertNotEqual(self.campaign.ballot_name, "Sem CSRF")

    def test_only_own_campaign_is_ever_shown(self):
        response = login("admin@b.com").get(URL)
        self.assertContains(response, self.other.slug)
        self.assertNotContains(response, self.campaign.slug)


class IdentitySaveTests(SettingsBase):
    def setUp(self):
        self.client = login("admin@a.com")

    def test_valid_save_updates_campaign_audits_names_only_and_flashes(self):
        response = self.client.post(URL, identity_payload())
        self.assertRedirects(response, URL + "#identidade", fetch_redirect_response=False)
        self.assertIn("Identidade da campanha salva.", self.messages(response))
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.candidate_name, "Maria Aparecida Souza")
        self.assertEqual(self.campaign.ballot_name, "Dra. Maria")
        self.assertEqual(self.campaign.ballot_number, "12345")
        self.assertEqual(self.campaign.primary_color, "#112233")
        self.assertEqual(self.campaign.voter_goal, 5000)

        log = self.audits().get()
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.entity, "Campaign")
        self.assertEqual(log.entity_id, str(self.campaign.pk))
        fields = log.details["fields"]
        self.assertIn("ballot_name", fields)
        self.assertIn("primary_color", fields)
        self.assertNotIn("logo_url", fields)
        self.assertNotIn("Dra. Maria", str(log.details))  # valores nunca vão para a auditoria
        self.assertNotIn("#112233", str(log.details))

    def test_unchanged_save_is_a_noop(self):
        self.client.post(URL, identity_payload())
        response = self.client.post(URL, identity_payload())
        self.assertEqual(response.status_code, 302)
        self.assertIn("Nenhuma alteração para salvar.", self.messages(response))
        self.assertEqual(self.audits().count(), 1)

    def test_only_changed_fields_are_listed(self):
        self.client.post(URL, identity_payload())
        self.client.post(URL, identity_payload(party="PYY"))
        last = self.audits().order_by("-created_at", "-id").first()
        self.assertEqual(last.details["fields"], ["party"])

    def test_invalid_color_rerenders_with_errors_and_saves_nothing(self):
        for bad in ("112233", "#12345", "red", "#zzzzzz", "javascript:1"):
            response = self.client.post(URL, identity_payload(primary_color=bad, ballot_name="Não deve salvar"))
            self.assertEqual(response.status_code, 200, bad)
            self.assertContains(response, "Use o formato hexadecimal #RRGGBB")
            self.assertContains(response, "Verifique os campos")  # via toast
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.primary_color, "#4f46e5")
        self.assertNotEqual(self.campaign.ballot_name, "Não deve salvar")
        self.assertEqual(self.audits().count(), 0)

    def test_invalid_form_keeps_typed_values(self):
        response = self.client.post(URL, identity_payload(primary_color="x", ballot_name="Digitado"))
        self.assertContains(response, 'value="Digitado"')

    def test_client_cannot_change_protected_campaign_fields(self):
        response = self.client.post(
            URL,
            identity_payload(slug="hackeada", status="SUSPENDED", campaign=str(self.other.pk), campaign_id=str(self.other.pk)),
        )
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.campaign.slug, "alfa")
        self.assertEqual(self.campaign.status, "ACTIVE")
        self.assertEqual(self.other.ballot_name, "Beta")  # a outra campanha jamais é tocada
        self.assertEqual(self.other.primary_color, "#4f46e5")

    def test_unknown_section_is_rejected(self):
        response = self.client.post(URL, {"section": "tudo", "ballot_name": "X"})
        self.assertRedirects(response, URL, fetch_redirect_response=False)
        self.assertIn("Requisição inválida.", self.messages(response))
        self.assertEqual(self.audits().count(), 0)

    def test_get_never_changes_state(self):
        self.client.get(URL + "?ballot_name=Hack&primary_color=%23000000")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.primary_color, "#4f46e5")

    def test_html_in_names_is_escaped_on_render(self):
        self.client.post(URL, identity_payload(ballot_name='<script>alert("x")</script>'))
        response = self.client.get(URL)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")


class LogoTests(SettingsBase):
    def setUp(self):
        self.client = login("admin@a.com")

    def test_replace_with_valid_png(self):
        url = data_url(png_bytes(16, 16))
        response = self.client.post(URL, identity_payload(logo_action="replace", logo_data=url))
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.logo_url, url)
        self.assertIn("logo_url", self.audits().get().details["fields"])
        self.assertNotIn(url[:60], str(self.audits().get().details))  # imagem nunca é auditada

    def test_saved_logo_is_rendered_on_page(self):
        url = data_url(jpeg_bytes(), "image/jpeg")
        self.client.post(URL, identity_payload(logo_action="replace", logo_data=url))
        response = self.client.get(URL)
        self.assertContains(response, 'id="portal-logo-state"')
        self.assertContains(response, url.split(",", 1)[1][:40])
        self.assertContains(response, "Remover")

    def test_rejects_wrong_mime(self):
        for bad in (
            "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
            "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "https://exemplo.com/logo.png",
        ):
            response = self.client.post(URL, identity_payload(logo_action="replace", logo_data=bad))
            self.assertEqual(response.status_code, 200, bad)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.logo_url, "")

    def test_rejects_declared_png_with_other_content(self):
        response = self.client.post(
            URL, identity_payload(logo_action="replace", logo_data=data_url(b"<html>nao sou imagem</html>", "image/png"))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "não corresponde a uma imagem válida")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.logo_url, "")

    def test_rejects_oversized_logo_and_keeps_previous(self):
        good = data_url(png_bytes())
        self.client.post(URL, identity_payload(logo_action="replace", logo_data=good))
        big = data_url(png_bytes() + b"\x00" * (310 * 1024))
        response = self.client.post(URL, identity_payload(logo_action="replace", logo_data=big, ballot_name="Outra"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "300 KB")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.logo_url, good)
        self.assertNotEqual(self.campaign.ballot_name, "Outra")

    def test_rejects_corrupted_base64(self):
        response = self.client.post(URL, identity_payload(logo_action="replace", logo_data="data:image/png;base64,@@@@"))
        self.assertEqual(response.status_code, 200)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.logo_url, "")

    def test_replace_without_data_is_an_error(self):
        response = self.client.post(URL, identity_payload(logo_action="replace", logo_data=""))
        self.assertEqual(response.status_code, 200)

    def test_data_is_ignored_unless_action_is_replace(self):
        response = self.client.post(URL, identity_payload(logo_action="keep", logo_data=data_url(png_bytes())))
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.logo_url, "")

    def test_remove_clears_logo(self):
        self.client.post(URL, identity_payload(logo_action="replace", logo_data=data_url(png_bytes())))
        response = self.client.post(URL, identity_payload(logo_action="remove"))
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.logo_url, "")
        self.assertIn("logo_url", self.audits().order_by("-created_at", "-id").first().details["fields"])

    def test_failed_save_keeps_new_logo_for_resubmission(self):
        url = data_url(png_bytes())
        response = self.client.post(URL, identity_payload(logo_action="replace", logo_data=url, primary_color="x"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["logo_action"], "replace")
        self.assertEqual(response.context["logo_echo"], url)

    def test_unsafe_stored_logo_is_not_rendered(self):
        Campaign.objects.filter(pk=self.campaign.pk).update(logo_url='javascript:alert(1)"onerror="x')
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        # a página de configurações só usa logos que passam na validação (o menu lateral é do layout compartilhado)
        self.assertEqual(response.context["saved_logo"], "")
        self.assertEqual(response.context["logo_state"]["saved"], "")


class PublicFormSaveTests(SettingsBase):
    def setUp(self):
        self.client = login("admin@a.com")

    def test_valid_save(self):
        response = self.client.post(URL, public_form_payload())
        self.assertRedirects(response, URL + "#formulario", fetch_redirect_response=False)
        self.assertIn("Formulário público salvo.", self.messages(response))
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.form_title, "Junte-se a nós")
        self.assertEqual(self.campaign.form_config["birth_date"], "hidden")
        self.assertEqual(self.campaign.form_config["address"], "required")
        self.assertEqual(self.campaign.consent_text, "")
        self.assertEqual(self.campaign.privacy_contact, "Maria · privacidade@exemplo.com.br")

        log = self.audits().get()
        self.assertEqual(log.details["section"], "formulario_publico")
        self.assertIn("form_title", log.details["fields"])
        self.assertIn("form_config", log.details["fields"])
        self.assertNotIn("Junte-se", str(log.details))

    def test_custom_consent_text_and_restore_default(self):
        text = "Autorizo {{candidato}} a usar meus dados para comunicação política, conforme a LGPD."
        self.client.post(URL, public_form_payload(consent_text=text))
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.consent_text, text)
        self.client.post(URL, public_form_payload(consent_text=""))  # "Restaurar texto padrão" envia vazio
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.consent_text, "")

    def test_invalid_mode_and_short_consent(self):
        response = self.client.post(URL, public_form_payload(config_email="talvez"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escolha oculto, opcional ou obrigatório.")
        response = self.client.post(URL, public_form_payload(consent_text="muito curto"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pelo menos 40 caracteres")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.form_title, "")
        self.assertEqual(self.audits().count(), 0)

    def test_unchanged_config_is_noop(self):
        self.client.post(URL, public_form_payload())
        response = self.client.post(URL, public_form_payload())
        self.assertIn("Nenhuma alteração para salvar.", self.messages(response))
        self.assertEqual(self.audits().count(), 1)

    def test_sections_are_independent(self):
        self.client.post(URL, public_form_payload())
        self.client.post(URL, identity_payload())
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.form_title, "Junte-se a nós")  # salvar a identidade não zera o formulário
        self.assertEqual(self.campaign.ballot_name, "Dra. Maria")

    def test_page_renders_mode_selectors_for_every_group(self):
        response = self.client.get(URL)
        for key in ("email", "birth_date", "gender", "address", "electoral"):
            self.assertContains(response, f'name="config_{key}"', count=3)  # Oculto / Opcional / Obrigatório
        for label in ("Oculto", "Opcional", "Obrigatório"):
            self.assertContains(response, label)
