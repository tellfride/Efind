"""Cadastro público pelo link/QR Code: formulário, duplicados, segurança e páginas de apoio."""

from django.core.cache import cache

from apps.auditlog.models import AuditLog
from apps.campaigns.models import Campaign
from apps.core.constants import DEFAULT_CONSENT_TEXT, CampaignStatus
from apps.voters.models import Voter

from .helpers import VoterTestCase, make_voter

VALID = {
    "name": "maria da silva",
    "phone": "(11) 98765-4321",
    "cep": "01310-100",
    "street": "avenida paulista",
    "number": "1000",
    "neighborhood": "bela vista",
    "city": "são paulo",
    "state": "SP",
    "consent": "on",
}


class PublicFormTests(VoterTestCase):
    def url(self, user=None, suffix=""):
        return f"/c/{(user or self.cabo1).invite_code}/{suffix}"

    def post(self, data=None, user=None, **extra):
        payload = {**VALID, **(data or {})}
        return self.client.post(self.url(user), payload, **extra)

    def test_get_renders_branded_form_without_login(self):
        Campaign.objects.filter(pk=self.a.pk).update(
            form_title="Junte-se a nós", form_message="Mensagem de boas-vindas", primary_color="#e11d48", logo_url=""
        )
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Junte-se a nós")
        self.assertContains(r, "Mensagem de boas-vindas")
        self.assertContains(r, "Indicado por Caio")
        self.assertContains(r, "#e11d48")
        self.assertContains(r, 'name="website"')  # honeypot
        self.assertContains(r, 'data-mask="cep"')
        self.assertContains(r, "data-cep-lookup")
        self.assertContains(r, 'name="whatsapp_opt_in"')
        self.assertContains(r, 'content="noindex, nofollow, noarchive"')
        self.assertEqual(r["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertNotContains(r, "checked")  # consentimentos nunca vêm marcados

    def test_default_title_and_consent_text_with_candidate_name(self):
        r = self.client.get(self.url())
        self.assertContains(r, "Cadastre-se e faça parte!")
        expected = DEFAULT_CONSENT_TEXT.replace("{{candidato}}", self.a.ballot_name)
        self.assertContains(r, expected[:80])
        self.assertContains(r, f"/c/{self.cabo1.invite_code}/privacidade/")

    def test_invalid_color_falls_back_to_default(self):
        Campaign.objects.filter(pk=self.a.pk).update(primary_color='red;background:url(x)')
        r = self.client.get(self.url())
        self.assertContains(r, "#4f46e5")
        self.assertNotContains(r, "url(x)")

    def test_unsafe_logo_is_not_rendered(self):
        Campaign.objects.filter(pk=self.a.pk).update(logo_url='javascript:alert(1)')
        r = self.client.get(self.url())
        self.assertNotContains(r, "javascript:alert")

    def test_invalid_inactive_or_suspended_links_are_404(self):
        self.assertEqual(self.client.get("/c/CODIGOINEXISTENTE/").status_code, 404)
        self.assertEqual(self.client.get("/c/a/").status_code, 404)  # formato inválido
        r = self.client.get("/c/CODIGOINEXISTENTE/")
        self.assertContains(r, "Link inválido ou desativado", status_code=404)
        self.cabo1.is_active = False
        self.cabo1.save()
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.post(self.url(), VALID).status_code, 404)
        self.assertEqual(Voter.objects.count(), 0)
        self.cabo1.is_active = True
        self.cabo1.save()
        Campaign.objects.filter(pk=self.a.pk).update(status=CampaignStatus.SUSPENDED)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.get(self.url(suffix="obrigado/")).status_code, 404)
        self.assertEqual(self.client.get(self.url(suffix="privacidade/")).status_code, 404)

    def test_post_creates_voter_linked_to_link_owner(self):
        r = self.post()
        self.assertRedirects(r, f"/c/{self.cabo1.invite_code}/obrigado/", fetch_redirect_response=False)
        v = Voter.objects.get()
        self.assertEqual(v.campaign_id, self.a.pk)
        self.assertEqual(v.registered_by_id, self.cabo1.pk)
        self.assertEqual(v.name, "Maria da Silva")
        self.assertEqual(v.phone, "5511987654321")
        self.assertEqual(v.cep, "01310100")
        self.assertEqual(v.street, "Avenida Paulista")
        self.assertEqual(v.neighborhood, "Bela Vista")
        self.assertEqual(v.source, "LINK")
        self.assertEqual(v.geo_status, "PENDING")
        self.assertIsNotNone(v.consent_at)
        self.assertEqual(v.consent_ip, "127.0.0.1")
        self.assertIn(self.a.ballot_name, v.consent_text)
        self.assertFalse(v.whatsapp_opt_in)
        self.assertIsNone(v.opt_out_at)
        self.geocode_public.assert_called_once_with(v.pk)

    def test_whatsapp_optin_and_qr_source(self):
        self.post({"whatsapp_opt_in": "on", "source": "QRCODE"})
        v = Voter.objects.get()
        self.assertTrue(v.whatsapp_opt_in)
        self.assertEqual(v.source, "QRCODE")

    def test_unknown_source_is_normalized_to_link(self):
        self.post({"source": "MANUAL"})
        self.assertEqual(Voter.objects.get().source, "LINK")

    def test_qr_query_pre_fills_hidden_source(self):
        r = self.client.get(self.url() + "?src=qr")
        self.assertContains(r, 'name="source" value="QRCODE"')
        r = self.client.get(self.url())
        self.assertContains(r, 'name="source" value="LINK"')

    def test_consent_is_required(self):
        data = {k: v for k, v in VALID.items() if k != "consent"}
        r = self.client.post(self.url(), data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "autorize o uso dos seus dados")
        self.assertEqual(Voter.objects.count(), 0)

    def test_validation_errors_keep_values_and_do_not_save(self):
        r = self.post({"phone": "123", "name": "Jo"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "telefone válido")
        self.assertContains(r, "Informe o nome completo")
        self.assertEqual(Voter.objects.count(), 0)

    def test_audit_has_no_personal_data(self):
        self.post()
        v = Voter.objects.get()
        log = AuditLog.objects.get(action="voter.public_register")
        self.assertEqual(log.user_id, self.cabo1.pk)
        self.assertEqual(log.campaign_id, self.a.pk)
        self.assertEqual(log.details, {"voter_id": str(v.pk), "source": "LINK"})
        self.assertNotIn("Maria", str(log.details))

    def test_thanks_page_has_share_button_with_same_link(self):
        r = self.client.get(self.url(suffix="obrigado/"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Compartilhe com seus amigos")
        self.assertContains(r, "https://wa.me/?text=")
        self.assertContains(r, f"%2Fc%2F{self.cabo1.invite_code}%2F")
        self.assertNotContains(r, "Seus dados foram atualizados")
        r = self.client.get(self.url(suffix="obrigado/") + "?r=updated")
        self.assertContains(r, "Seus dados foram atualizados")

    def test_privacy_page(self):
        Campaign.objects.filter(pk=self.a.pk).update(privacy_contact="privacidade@campanha.com.br")
        r = self.client.get(self.url(suffix="privacidade/"))
        self.assertEqual(r.status_code, 200)
        for text in ("privacidade@campanha.com.br", "art. 7º, I", "SAIR", "E-Find", "art. 18", "Candidato Alfa"):
            self.assertContains(r, text)
        self.assertEqual(r["X-Robots-Tag"], "noindex, nofollow, noarchive")

    def test_method_not_allowed(self):
        self.assertEqual(self.client.put(self.url()).status_code, 405)
        self.assertEqual(self.client.post(self.url(suffix="obrigado/")).status_code, 405)


class FormConfigTests(VoterTestCase):
    def test_config_hides_and_requires_groups(self):
        Campaign.objects.filter(pk=self.a.pk).update(
            form_config={"email": "required", "birth_date": "hidden", "gender": "hidden", "address": "hidden", "electoral": "required"}
        )
        url = f"/c/{self.cabo1.invite_code}/"
        r = self.client.get(url)
        self.assertContains(r, 'name="email"')
        self.assertContains(r, 'name="electoral_zone"')
        self.assertNotContains(r, 'name="cep"')
        self.assertNotContains(r, 'name="birth_date"')
        self.assertNotContains(r, 'name="gender"')
        # sem e-mail/zona → erro; com tudo → grava e ignora campos ocultos enviados à força
        r = self.client.post(url, {"name": "João Pereira", "phone": "11987654321", "consent": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Voter.objects.count(), 0)
        r = self.client.post(
            url,
            {
                "name": "João Pereira", "phone": "11987654321", "consent": "on", "email": "JOAO@Exemplo.com",
                "electoral_zone": "025", "electoral_section": "120", "city": "Hackeada", "birth_date": "01/01/1990",
            },
        )
        self.assertEqual(r.status_code, 302)
        v = Voter.objects.get()
        self.assertEqual((v.email, v.electoral_zone, v.electoral_section), ("joao@exemplo.com", "25", "120"))
        self.assertEqual(v.city, "")  # grupo oculto: nunca confia no cliente
        self.assertIsNone(v.birth_date)

    def test_default_config_requires_address(self):
        url = f"/c/{self.cabo1.invite_code}/"
        r = self.client.post(url, {"name": "João Pereira", "phone": "11987654321", "consent": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Informe o CEP")
        self.assertEqual(Voter.objects.count(), 0)

    def test_birth_date_age_range(self):
        Campaign.objects.filter(pk=self.a.pk).update(form_config={"address": "optional"})
        url = f"/c/{self.cabo1.invite_code}/"
        base = {"name": "João Pereira", "phone": "11987654321", "consent": "on"}
        r = self.client.post(url, {**base, "birth_date": "01/01/2020"})
        self.assertContains(r, "entre 16 e 120")
        r = self.client.post(url, {**base, "birth_date": "31/02/1990"})
        self.assertContains(r, "Data inválida")
        r = self.client.post(url, {**base, "birth_date": "15/03/1985"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Voter.objects.get().birth_date.isoformat(), "1985-03-15")


class DuplicateTests(VoterTestCase):
    def setUp(self):
        super().setUp()
        self.url = f"/c/{self.cabo2.invite_code}/"
        self.existing = make_voter(
            self.a, self.cabo1, name="Maria Original", phone="5511987654321", email="", neighborhood="Centro",
            whatsapp_opt_in=False, opt_out_at=None,
        )

    def test_duplicate_phone_never_reveals_data_and_keeps_owner(self):
        r = self.client.post(self.url, {**VALID, "name": "Outra Pessoa", "email": "novo@exemplo.com"})
        self.assertRedirects(r, f"/c/{self.cabo2.invite_code}/obrigado/?r=updated", fetch_redirect_response=False)
        self.assertEqual(Voter.objects.count(), 1)
        v = Voter.objects.get()
        self.assertEqual(v.pk, self.existing.pk)
        self.assertEqual(v.registered_by_id, self.cabo1.pk)  # mantém quem cadastrou
        self.assertEqual(v.name, "Maria Original")  # não sobrescreve
        self.assertEqual(v.neighborhood, "Centro")  # já preenchido: não muda
        self.assertEqual(v.email, "novo@exemplo.com")  # estava vazio: completa
        self.assertEqual(v.street, "Avenida Paulista")  # estava vazio: completa
        self.assertIsNotNone(v.consent_at)
        self.assertEqual(v.consent_ip, "127.0.0.1")
        self.assertFalse(v.whatsapp_opt_in)  # caixa não marcada agora
        self.geocode_public.assert_called_once()

    def test_response_for_duplicate_does_not_contain_existing_data(self):
        r = self.client.post(self.url, {**VALID, "name": "Outra Pessoa"}, follow=True)
        self.assertNotContains(r, "Maria Original")
        self.assertNotContains(r, "Centro")
        self.assertContains(r, "Seus dados foram atualizados")

    def test_opt_in_reactivates_only_when_checked_now(self):
        Voter.objects.filter(pk=self.existing.pk).update(whatsapp_opt_in=True, opt_out_at="2026-01-01T00:00:00Z")
        self.client.post(self.url, VALID)
        v = Voter.objects.get()
        self.assertTrue(v.whatsapp_opt_in)
        self.assertIsNotNone(v.opt_out_at)  # sem marcar de novo, continua descadastrado
        cache.clear()
        self.client.post(self.url, {**VALID, "whatsapp_opt_in": "on"})
        v.refresh_from_db()
        self.assertTrue(v.whatsapp_opt_in)
        self.assertIsNone(v.opt_out_at)

    def test_same_phone_in_other_campaign_is_not_a_duplicate(self):
        other = make_voter(self.b, self.admin_b, phone="5511987654321")
        self.client.post(self.url, VALID)
        self.assertEqual(Voter.objects.count(), 2)
        other.refresh_from_db()
        self.assertEqual(other.email, "")  # a outra campanha não foi tocada

    def test_duplicate_audit_has_only_ids_and_field_names(self):
        self.client.post(self.url, VALID)
        log = AuditLog.objects.get(action="voter.update")
        self.assertEqual(log.details["via"], "public_form")
        self.assertNotIn("98765", str(log.details))


class AntiAbuseTests(VoterTestCase):
    def test_honeypot_discards_silently(self):
        url = f"/c/{self.cabo1.invite_code}/"
        r = self.client.post(url, {**VALID, "website": "http://spam.example"})
        self.assertRedirects(r, f"/c/{self.cabo1.invite_code}/obrigado/", fetch_redirect_response=False)
        self.assertEqual(Voter.objects.count(), 0)

    def test_rate_limit_per_ip(self):
        url = f"/c/{self.cabo1.invite_code}/"
        for i in range(10):
            self.client.post(url, {**VALID, "phone": f"1198765{i:04d}"})
        r = self.client.post(url, {**VALID, "phone": "11999990000"})
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, "Muitas tentativas", status_code=429)
        self.assertEqual(Voter.objects.filter(phone="5511999990000").count(), 0)

    def test_csrf_is_enforced(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        r = strict.post(f"/c/{self.cabo1.invite_code}/", VALID)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Voter.objects.count(), 0)
