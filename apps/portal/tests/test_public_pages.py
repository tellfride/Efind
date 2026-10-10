"""Site público: landing, privacidade e termos."""

import re

from django.test import Client, TestCase

from apps.accounts.models import User

from .helpers import PASSWORD, Role, fast_hashing, login, make_campaign, make_user


@fast_hashing
class PublicPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("alfa")
        cls.admin = make_user(cls.campaign, "admin@a.com", Role.ADMIN)
        cls.cabo = make_user(cls.campaign, "cabo@a.com", Role.CABO, parent=cls.admin)
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD, name="Suporte")

    # --- Landing -----------------------------------------------------------------------------------------
    def test_landing_for_anonymous(self):
        response = Client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portal/landing.html")
        self.assertContains(response, "Organize sua campanha")
        self.assertContains(response, "do cabo eleitoral ao candidato")
        self.assertContains(response, 'href="/login/"')
        self.assertContains(response, "Acessar painel")
        self.assertNotContains(response, "Ir para o painel")
        self.assertContains(response, "mailto:contato@efind.com.br")
        self.assertContains(response, "Fale conosco")

    def test_landing_sections(self):
        text = Client().get("/").content.decode("utf-8")
        for expected in (
            "Como funciona",
            "Cadastre a equipe",
            "Cada cabo recebe seu link e QR Code",
            "Eleitores se cadastram",
            "Acompanhe no mapa e nos dashboards",
            "Comunique-se pelo WhatsApp oficial",
            "Recursos",
            "Hierarquia e permissões",
            "Cadastro por QR Code",
            "Mapa por bairro via CEP",
            "Dashboards personalizáveis",
            "Disparos de WhatsApp com modelos",
            "Auditoria completa",
            "Segurança e conformidade",
            "LGPD",
            "Lei nº 9.504/1997",
            'href="/privacidade/"',
            'href="/termos/"',
        ):
            self.assertIn(expected, text, expected)

    def test_landing_has_no_external_assets(self):
        text = Client().get("/").content.decode("utf-8")
        self.assertNotIn("<img", text)
        self.assertNotIn("http://", text.replace("http://www.w3.org/2000/svg", ""))
        # único https:// permitido são links de navegação (nenhum recurso externo)
        self.assertNotIn("src=\"https://", text)

    def test_landing_cta_for_campaign_user(self):
        for email in ("admin@a.com", "cabo@a.com"):
            response = login(email).get("/")
            self.assertEqual(response.status_code, 200, email)
            self.assertContains(response, "Ir para o painel")
            self.assertContains(response, 'href="/painel/"')
            self.assertNotContains(response, "Acessar painel")

    def test_landing_cta_for_super_admin(self):
        response = login("super@x.com").get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/super/"')
        self.assertContains(response, "Ir para o painel")

    def test_landing_does_not_leak_campaign_data(self):
        response = login("admin@a.com").get("/")
        self.assertNotContains(response, "admin@a.com")

    # --- Páginas legais ----------------------------------------------------------------------------------
    def test_privacy_page(self):
        for client in (Client(), login("admin@a.com")):
            response = client.get("/privacidade/")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Política de privacidade")
            self.assertContains(response, "Última atualização: outubro de 2026")
            self.assertContains(response, "contato@efind.com.br")
            self.assertContains(response, "controladora")
            self.assertContains(response, "operador")
            self.assertContains(response, "AES-256-GCM")
            self.assertContains(response, "auditoria")
            self.assertContains(response, "Direitos do titular")
            self.assertContains(response, 'href="/termos/"')

    def test_terms_page(self):
        for client in (Client(), login("cabo@a.com")):
            response = client.get("/termos/")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Termos de uso")
            self.assertContains(response, "Última atualização: outubro de 2026")
            self.assertContains(response, "Lei nº 9.504/1997")
            self.assertContains(response, "Resolução TSE nº 23.610/2019")
            self.assertContains(response, "listas de contatos compradas")
            self.assertContains(response, "ferramentas não oficiais de WhatsApp")
            self.assertContains(response, "suspender")
            self.assertContains(response, 'href="/privacidade/"')

    def test_legal_pages_super_admin_and_headings_anchors(self):
        client = login("super@x.com")
        for url in ("/privacidade/", "/termos/"):
            response = client.get(url)
            self.assertEqual(response.status_code, 200, url)
            text = response.content.decode("utf-8")
            # cada item do índice aponta para uma seção existente
            for anchor in re.findall(r'href="#([a-z-]+)"', text):
                self.assertIn(f'id="{anchor}"', text, f"{url}: âncora #{anchor}")

    def test_public_pages_accept_only_safe_methods(self):
        client = Client()
        for url in ("/", "/privacidade/", "/termos/"):
            self.assertEqual(client.get(url).status_code, 200)
            self.assertEqual(client.head(url).status_code, 200)
            self.assertEqual(client.post(url).status_code, 405, url)

    def test_footer_links_present_on_public_pages(self):
        for url in ("/", "/privacidade/", "/termos/"):
            text = Client().get(url).content.decode("utf-8")
            self.assertIn('href="/privacidade/"', text)
            self.assertIn('href="/termos/"', text)
