"""Endereços antigos (/painel/eleitores/...) redirecionam para /painel/apoiadores/..., sem perder caminho nem filtros."""

import uuid

from django.test import TestCase

from apps.core.constants import Role

from .helpers import PASSWORD, make_campaign, make_user


class LegacyRedirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("antigo")
        cls.admin = make_user(cls.campaign, "adm@antigo.com", Role.ADMIN)

    def test_list_redirects_permanently(self):
        response = self.client.get("/painel/eleitores/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/painel/apoiadores/")

    def test_subpaths_and_query_string_are_kept(self):
        voter_id = uuid.uuid4()
        response = self.client.get(f"/painel/eleitores/{voter_id}/editar/")
        self.assertEqual(response["Location"], f"/painel/apoiadores/{voter_id}/editar/")
        response = self.client.get("/painel/eleitores/", {"q": "maria", "page": "2"})
        self.assertEqual(response["Location"], "/painel/apoiadores/?q=maria&page=2")
        self.assertEqual(self.client.get("/painel/eleitores/importar/modelo/")["Location"], "/painel/apoiadores/importar/modelo/")

    def test_redirect_never_leaves_the_site(self):
        for tail in ("//exemplo.com", "/\\exemplo.com", "https://exemplo.com"):
            location = self.client.get("/painel/eleitores/" + tail)["Location"]
            self.assertTrue(location.startswith("/painel/apoiadores/"), location)

    def test_new_address_works_and_old_one_is_not_linked_from_the_panel(self):
        self.assertTrue(self.client.login(username="adm@antigo.com", password=PASSWORD))
        page = self.client.get("/painel/apoiadores/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "/painel/eleitores/")
        self.assertContains(page, 'href="/painel/apoiadores/"')  # menu lateral
