"""Modelo de planilha para download na importação de eleitores: arquivo servido pelo servidor, reconhecido pelo
próprio importador e com exemplos que nunca viram eleitores por engano."""

import codecs

from django.test import TestCase

from apps.accounts.models import UserPermission
from apps.core.constants import Role
from apps.voters.csv_import import (
    COLUMN_GUIDE,
    IMPORT_FIELDS,
    SAMPLE_COLUMNS,
    TEMPLATE_EXAMPLE_ROWS,
    auto_map_headers,
    build_import_records,
    build_template_csv,
    missing_required_fields,
    parse_csv,
    validate_import_record,
    validate_records,
)

from .helpers import PASSWORD, make_campaign, make_user

URL = "/painel/eleitores/importar/modelo/"


class TemplateFileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("modelo")
        cls.admin = make_user(cls.campaign, "adm@modelo.com", Role.ADMIN)
        cls.cabo = make_user(cls.campaign, "cabo@modelo.com", Role.CABO, parent=cls.admin)

    def login(self, email):
        self.client.logout()
        self.assertTrue(self.client.login(username=email, password=PASSWORD))

    def test_download_is_a_csv_attachment_with_utf8_bom(self):
        self.login("cabo@modelo.com")
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn('attachment; filename="modelo-importacao-eleitores.csv"', response["Content-Disposition"])
        self.assertTrue(response.content.startswith(codecs.BOM_UTF8))  # o Excel reconhece acentos
        self.assertIn(b"\r\n", response.content)

    def test_the_importer_recognises_every_column_of_the_downloaded_file(self):
        self.login("adm@modelo.com")
        text = self.client.get(URL).content.decode("utf-8")
        parsed = parse_csv(text)
        self.assertEqual(parsed.separator, ";")
        mapping = auto_map_headers(parsed.rows[0])
        self.assertEqual(mapping, [f.key for f in IMPORT_FIELDS])  # todas as 16 colunas, na ordem, sem ajuste manual
        self.assertEqual(mapping, list(SAMPLE_COLUMNS))
        self.assertEqual(missing_required_fields(mapping), [])

    def test_example_rows_are_rejected_if_the_user_forgets_to_delete_them(self):
        text = build_template_csv()
        parsed = parse_csv(text)
        records = build_import_records(parsed, auto_map_headers(parsed.rows[0]), has_header=True)
        results = validate_records(records)
        self.assertEqual(len(results), len(TEMPLATE_EXAMPLE_ROWS))
        for result in results:
            self.assertIsNone(result.voter)  # nenhum eleitor fictício é criado
            self.assertTrue(any("Telefone inválido" in e for e in result.errors))

    def test_example_rows_show_valid_formats_for_every_other_column(self):
        for row in TEMPLATE_EXAMPLE_ROWS:
            values = dict(zip(SAMPLE_COLUMNS, row, strict=True))
            values["telefone"] = "(11) 98765-4321"  # troca só o telefone proposital inválido
            validation = validate_import_record(values)
            self.assertIsNotNone(validation.voter, validation.errors)
            self.assertEqual(validation.errors, [])
            self.assertEqual(validation.warnings, [], values)  # data, gênero, apoio, UF, CEP... todos aceitos

    def test_guide_covers_every_import_field_in_order_with_the_right_required_flags(self):
        self.assertEqual([c["key"] for c in COLUMN_GUIDE], [f.key for f in IMPORT_FIELDS])
        self.assertEqual({c["key"] for c in COLUMN_GUIDE if c["required"]}, {"nome", "telefone"})
        for column in COLUMN_GUIDE:
            self.assertTrue(column["format"] and column["example"], column)
        self.assertEqual(TEMPLATE_EXAMPLE_ROWS[0][SAMPLE_COLUMNS.index("telefone")][:4], "(00)")  # inválido de propósito

    def test_import_page_links_the_server_file_and_shows_the_guide(self):
        self.login("adm@modelo.com")
        page = self.client.get("/painel/eleitores/importar/")
        self.assertContains(page, f'href="{URL}"')
        self.assertContains(page, "Baixar modelo de planilha")
        self.assertContains(page, "Como preencher a planilha")
        self.assertContains(page, "Apague as <strong>2 linhas de exemplo</strong>")
        self.assertContains(page, 'badge badge-red">Obrigatório', count=2)  # só nome e telefone
        for column in COLUMN_GUIDE:
            self.assertContains(page, f'<td class="font-mono text-xs">{column["key"]}</td>')

    def test_requires_login_and_the_create_permission(self):
        self.client.logout()
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))

        self.login("cabo@modelo.com")  # o cabo cria eleitores por padrão
        self.assertEqual(self.client.get(URL).status_code, 200)
        UserPermission.objects.update_or_create(user=self.cabo, module="eleitores", defaults={"can_create": False})
        self.assertEqual(self.client.get(URL).status_code, 403)  # sem permissão de criar, sem modelo

    def test_only_get_is_allowed(self):
        self.login("adm@modelo.com")
        self.assertEqual(self.client.post(URL).status_code, 405)
