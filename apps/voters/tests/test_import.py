"""Importação por CSV: leitor, mapeamento automático, validação por linha, análise e fluxos HTTP."""

import json
from datetime import date

from django.test import SimpleTestCase

from apps.auditlog.models import AuditLog
from apps.core.constants import Role
from apps.voters.csv_import import (
    CsvParseError,
    auto_map_headers,
    build_import_records,
    clean_mapping,
    detect_separator,
    missing_required_fields,
    parse_csv,
    split_file_duplicates,
    validate_import_record,
    validate_records,
)
from apps.voters.import_service import analyze_import, guess_mapping_from_data, looks_like_header
from apps.voters.models import Voter

from .helpers import VoterTestCase, make_user, make_voter

TODAY = date(2026, 10, 10)


class ParserTests(SimpleTestCase):
    def test_detects_separator(self):
        self.assertEqual(detect_separator("nome;telefone\nA;1"), ";")
        self.assertEqual(detect_separator("nome,telefone\nA,1"), ",")
        self.assertEqual(detect_separator("nome\ttelefone\nA\t1"), "\t")
        self.assertEqual(detect_separator('"a,b";c\n1;2'), ";")  # vírgula entre aspas não conta
        self.assertEqual(detect_separator("sep=,\nnome,telefone"), ",")
        self.assertEqual(detect_separator("só uma coluna"), ";")

    def test_parses_quotes_escaped_quotes_and_newlines(self):
        text = 'nome;obs\r\n"Silva; Maria";"disse ""oi"""\r\n"João\nPedro";x\r\n'
        parsed = parse_csv(text)
        self.assertEqual(parsed.rows[1], ["Silva; Maria", 'disse "oi"'])
        self.assertEqual(parsed.rows[2], ["João\nPedro", "x"])
        self.assertEqual(parsed.lines, [1, 2, 3])  # linha física onde cada registro começa

    def test_bom_blank_lines_and_sep_directive(self):
        parsed = parse_csv("﻿sep=;\nnome;telefone\n\n  ;  \nAna;11\n")
        self.assertEqual(parsed.separator, ";")
        self.assertEqual(parsed.rows, [["nome", "telefone"], ["Ana", "11"]])
        self.assertEqual(parsed.lines, [2, 5])

    def test_explicit_separator_and_invalid_separator(self):
        self.assertEqual(parse_csv("a|b", separator=",").rows, [["a|b"]])
        with self.assertRaises(CsvParseError):
            parse_csv("a", separator="|")

    def test_null_bytes_removed(self):
        self.assertEqual(parse_csv("a\x00b;c").rows, [["ab", "c"]])


class MappingTests(SimpleTestCase):
    def test_auto_map_exact_and_fuzzy(self):
        headers = ["Nome Completo", "Celular", "E-mail", "Data de Nascimento", "Sexo", "CEP", "Endereço", "Nº", "Bairro", "Município", "UF", "Zona Eleitoral", "Seção", "Observação"]
        mapping = auto_map_headers(headers)
        self.assertEqual(
            mapping,
            ["nome", "telefone", "email", "nascimento", "genero", "cep", "rua", "numero", "bairro", "cidade", "uf", "zona", "secao", ""],
        )

    def test_each_field_used_once(self):
        mapping = auto_map_headers(["Nome", "Nome do eleitor", "Telefone", "Whatsapp"])
        self.assertEqual(mapping.count("nome"), 1)
        self.assertEqual(mapping.count("telefone"), 1)

    def test_clean_mapping_validates_client_input(self):
        self.assertEqual(clean_mapping(["nome", "", "telefone"], 4), ["nome", "", "telefone", ""])
        self.assertEqual(clean_mapping(["nome", "telefone", "email"], 2), ["nome", "telefone"])
        for bad in ("nome", None, {"a": 1}, ["nome", "campo_inexistente"], ["nome", "nome"]):
            with self.assertRaises(ValueError):
                clean_mapping(bad, 3)
        self.assertEqual(clean_mapping(["nome", 5, None], 3), ["nome", "", ""])

    def test_missing_required(self):
        self.assertEqual(missing_required_fields(["nome", ""]), ["telefone"])
        self.assertEqual(missing_required_fields(["nome", "telefone"]), [])

    def test_header_detection_and_content_guess(self):
        self.assertTrue(looks_like_header(parse_csv("Nome;Telefone\nAna;11999990000")))
        self.assertFalse(looks_like_header(parse_csv("Ana Souza;11999990000\nBeto;11999990001")))
        self.assertEqual(
            guess_mapping_from_data(["Ana Souza", "(11) 99999-0000", "ana@x.com", "x"], 4),
            ["nome", "telefone", "email", ""],
        )

    def test_build_records_skips_header_and_uses_original_line_numbers(self):
        parsed = parse_csv("nome;telefone;extra\nAna;11999990000;z\n\nBeto;11999990001")
        records = build_import_records(parsed, ["nome", "telefone", ""], True)
        self.assertEqual([r.row for r in records], [2, 4])
        self.assertEqual(records[0].values, {"nome": "Ana", "telefone": "11999990000"})
        records = build_import_records(parsed, ["nome", "telefone", ""], False)
        self.assertEqual(len(records), 3)


class RowValidationTests(SimpleTestCase):
    def validate(self, **values):
        return validate_import_record(values, TODAY)

    def test_valid_row_is_normalized(self):
        r = self.validate(
            nome="MARIA DA SILVA", telefone="(11) 98765-4321", email="Maria@Exemplo.COM", nascimento="15/03/1985",
            genero="feminino", cep="01310-100", rua="avenida paulista", numero="1000", bairro="BELA VISTA", cidade="são paulo",
            uf="sp", zona="025", secao="0120", apoio="apoiadora", tags="Saúde; Jovem|Líder",
        )
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])
        v = r.voter
        self.assertEqual(v["name"], "Maria da Silva")
        self.assertEqual(v["phone"], "5511987654321")
        self.assertEqual(v["email"], "maria@exemplo.com")
        self.assertEqual(v["birth_date"], date(1985, 3, 15))
        self.assertEqual((v["gender"], v["cep"], v["state"]), ("F", "01310100", "SP"))
        self.assertEqual((v["street"], v["neighborhood"], v["city"]), ("Avenida Paulista", "Bela Vista", "São Paulo"))
        self.assertEqual((v["electoral_zone"], v["electoral_section"]), ("25", "120"))
        self.assertEqual(v["support_level"], "APOIADOR")
        self.assertEqual(v["tags"], ",saude,jovem,lider,")

    def test_iso_birth_date(self):
        self.assertEqual(self.validate(nome="Ana Souza", telefone="11999990000", nascimento="1990-12-31").voter["birth_date"], date(1990, 12, 31))

    def test_required_fields(self):
        r = self.validate(nome="Al", telefone="")
        self.assertIsNone(r.voter)
        self.assertEqual(r.errors, ["Nome ausente ou muito curto", "Telefone ausente"])
        self.assertEqual(self.validate(nome="Ana Souza", telefone="123").errors, ["Telefone inválido (use DDD + número)"])
        self.assertIn("Nome ausente", self.validate(nome="12345", telefone="11999990000").errors[0])
        self.assertIn("120 caracteres", self.validate(nome="A" * 130, telefone="11999990000").errors[0])

    def test_invalid_optionals_become_warnings_and_row_is_kept(self):
        r = self.validate(
            nome="Ana Souza", telefone="11999990000", email="sem-arroba", nascimento="31/02/1990", genero="xyz", cep="123",
            uf="XX", zona="abc", secao="99999999", apoio="talvez",
        )
        self.assertEqual(r.errors, [])
        self.assertEqual(len(r.warnings), 8)
        self.assertEqual(r.voter["email"], "")
        self.assertIsNone(r.voter["birth_date"])
        self.assertEqual((r.voter["gender"], r.voter["cep"], r.voter["state"], r.voter["support_level"]), ("", "", "", ""))

    def test_age_out_of_range_is_dropped_with_warning(self):
        r = self.validate(nome="Ana Souza", telefone="11999990000", nascimento="01/01/2020")
        self.assertIsNone(r.voter["birth_date"])
        self.assertTrue(any("Idade fora do intervalo" in w for w in r.warnings))

    def test_long_fields_are_truncated(self):
        r = self.validate(nome="Ana Souza", telefone="11999990000", rua="r" * 500, complemento="c" * 500, numero="9" * 50)
        self.assertEqual(len(r.voter["street"]), 160)
        self.assertEqual(len(r.voter["complement"]), 100)
        self.assertEqual(len(r.voter["number"]), 20)

    def test_file_duplicates_keep_first_occurrence(self):
        parsed = parse_csv("nome;telefone\nAna Souza;11999990000\nAna de novo;(11) 99999-0000\nXx;1\nBeto Lima;11999990001")
        results = validate_records(build_import_records(parsed, ["nome", "telefone"], True), TODAY)
        unique, repeated = split_file_duplicates(results)
        self.assertEqual([r.voter["name"] for r in unique], ["Ana Souza", "Beto Lima"])
        self.assertEqual([r.row for r in repeated], [3])
        self.assertEqual(len([r for r in results if r.voter is None]), 1)


class AnalysisTests(VoterTestCase):
    def test_analysis_flags_existing_and_repeated(self):
        make_voter(self.a, self.cabo1, phone="5511999990000")
        make_voter(self.b, self.admin_b, phone="5511999990001")  # outra campanha: não conta como duplicado
        text = "nome;telefone\nAna Souza;11999990000\nBeto Lima;11999990001\nBeto Lima;11999990001\nCa;1\n"
        a = analyze_import(text, self.a.pk, today=TODAY)
        self.assertEqual(a.mapping, ["nome", "telefone"])
        self.assertTrue(a.has_header)
        self.assertEqual([r.voter["name"] for r in a.to_import], ["Beto Lima"])
        self.assertEqual(len(a.already_registered), 1)
        self.assertEqual(len(a.repeated), 1)
        self.assertEqual(len(a.invalid), 1)

    def test_missing_required_stops_before_validation(self):
        a = analyze_import("nome;email\nAna Souza;a@b.com", self.a.pk)
        self.assertEqual(a.missing_required, ["telefone"])
        self.assertEqual(a.results, [])

    def test_over_limit(self):
        rows = "\n".join(f"Pessoa {i:05d};11{900000000 + i}" for i in range(5001))
        a = analyze_import("nome;telefone\n" + rows, self.a.pk)
        self.assertTrue(a.over_limit)
        self.assertEqual(a.results, [])

    def test_empty_and_huge_input(self):
        with self.assertRaises(CsvParseError):
            analyze_import("  \n ", self.a.pk)
        with self.assertRaises(CsvParseError):
            analyze_import("x" * 4_000_001, self.a.pk)


class ImportViewTests(VoterTestCase):
    URL = "/painel/eleitores/importar/"
    PREVIEW = "/api/painel/eleitores/importar/previa/"
    CSV = (
        "Nome;Telefone;Bairro;Nascimento\n"
        "ana souza;(11) 99999-0001;centro;10/05/1990\n"
        "Beto Lima;11999990002;cambuí;\n"
        "Beto Lima de novo;11999990002;x;\n"
        "Inválido;123;x;\n"
    )

    def post(self, data=None, **extra):
        payload = {
            "csv_text": self.CSV,
            "mapping": json.dumps(["nome", "telefone", "bairro", "nascimento"]),
            "has_header": "on",
            "declaration": "on",
        }
        payload.update(data or {})
        return self.client.post(self.URL, payload, **extra)

    def preview(self, body, user=None):
        self.login(user or self.admin)
        return self.client.post(self.PREVIEW, json.dumps(body), content_type="application/json")

    # --- página -------------------------------------------------------------------------------
    def test_page_renders_with_required_texts(self):
        self.login(self.cabo1)
        r = self.client.get(self.URL)
        self.assertContains(r, "Declaro que os eleitores desta lista consentiram com o tratamento de seus dados (LGPD).")
        self.assertContains(r, "mensagens de WhatsApp")
        self.assertContains(r, "import-config")
        self.assertNotContains(r, "Cadastrar em nome de")  # cabo importa sempre para si
        self.login(self.admin)
        r = self.client.get(self.URL)
        self.assertContains(r, "Cadastrar em nome de")
        self.assertContains(r, f'<option value="{self.admin.pk}" selected>')  # padrão: o próprio usuário

    def test_requires_create_permission(self):
        from apps.accounts.models import RolePermission

        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="eleitores").update(can_create=False)
        self.login(self.cabo1)
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.client.post(self.PREVIEW, "{}", content_type="application/json").status_code, 403)
        self.assertEqual(Voter.objects.count(), 0)

    # --- pré-visualização ---------------------------------------------------------------------
    def test_preview_auto_maps_and_validates_on_server(self):
        make_voter(self.a, self.cabo1, phone="5511999990001")
        r = self.preview({"csv_text": self.CSV})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["has_header"])
        self.assertEqual(data["mapping"], ["nome", "telefone", "bairro", "nascimento"])
        self.assertEqual(data["total_rows"], 4)
        self.assertEqual(data["summary"]["will_import"], 1)
        self.assertEqual(data["summary"]["already_registered"], 1)
        self.assertEqual(data["summary"]["invalid"], 1)
        self.assertEqual(data["summary"]["repeated_in_file"], 1)
        self.assertTrue(data["ready"])
        self.assertEqual(len(data["preview"]), 4)
        self.assertEqual([p["status"] for p in data["preview"]], ["duplicate_campaign", "ok", "duplicate_file", "invalid"])
        self.assertEqual(data["preview"][-1]["status"], "invalid")
        self.assertIn("Telefone inválido", data["preview"][-1]["errors"][0])
        self.assertEqual(Voter.objects.count(), 1)  # pré-visualizar nunca grava

    def test_preview_manual_mapping_and_missing_required(self):
        data = self.preview({"csv_text": "a;b\nAna Souza;11999990001", "has_header": True, "mapping": ["nome", ""]}).json()
        self.assertEqual(data["missing_required"], ["Telefone / WhatsApp"])
        self.assertFalse(data["ready"])
        data = self.preview({"csv_text": "a;b\nAna Souza;11999990001", "has_header": True, "mapping": ["nome", "telefone"]}).json()
        self.assertTrue(data["ready"])

    def test_preview_rejects_bad_input(self):
        for body in ({"csv_text": ""}, {"csv_text": 5}, {"csv_text": "a;b", "mapping": "nome"}, {"csv_text": "nome;telefone", "mapping": ["x", "y"]}, {"csv_text": "a", "has_header": "sim"}, []):
            self.assertEqual(self.preview(body).status_code, 400, body)
        self.login(self.admin)
        self.assertEqual(self.client.post(self.PREVIEW, "não é json", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(self.PREVIEW).status_code, 405)

    def test_preview_is_scoped_to_campaign(self):
        make_voter(self.b, self.admin_b, phone="5511999990001")  # só existe na outra campanha
        data = self.preview({"csv_text": self.CSV}).json()
        self.assertEqual(data["summary"]["already_registered"], 0)

    # --- importação ---------------------------------------------------------------------------
    def test_import_flow_and_result_page(self):
        self.login(self.cabo1)
        r = self.post({"whatsapp_opt_in": "on"})
        self.assertRedirects(r, "/painel/eleitores/importar/resultado/", fetch_redirect_response=False)
        voters = Voter.objects.order_by("name")
        self.assertEqual([v.name for v in voters], ["Ana Souza", "Beto Lima"])
        v = voters[0]
        self.assertEqual(v.registered_by_id, self.cabo1.pk)
        self.assertEqual(v.campaign_id, self.a.pk)
        self.assertEqual(v.source, "IMPORT")
        self.assertEqual(v.geo_status, "PENDING")
        self.assertTrue(v.whatsapp_opt_in)
        self.assertIsNotNone(v.consent_at)
        self.assertIn("consentiram", v.consent_text)
        self.assertEqual(v.neighborhood, "Centro")
        self.assertEqual(v.birth_date, date(1990, 5, 10))
        log = AuditLog.objects.get(action="voter.import")
        self.assertEqual(
            {k: log.details[k] for k in ("total", "imported", "duplicates", "invalid", "whatsapp_opt_in")},
            {"total": 4, "imported": 2, "duplicates": 1, "invalid": 1, "whatsapp_opt_in": True},
        )
        page = self.client.get("/painel/eleitores/importar/resultado/")
        self.assertContains(page, "Importação concluída")
        self.assertContains(page, "Telefone repetido no arquivo")
        self.assertContains(page, "Telefone inválido")
        # o resultado só aparece uma vez
        self.assertRedirects(self.client.get("/painel/eleitores/importar/resultado/"), self.URL, fetch_redirect_response=False)

    def test_import_without_whatsapp_checkbox_does_not_opt_in(self):
        self.login(self.cabo1)
        self.post()
        self.assertFalse(Voter.objects.filter(whatsapp_opt_in=True).exists())

    def test_declaration_is_required(self):
        self.login(self.cabo1)
        data = {"csv_text": self.CSV, "mapping": json.dumps(["nome", "telefone", "bairro", "nascimento"]), "has_header": "on"}
        r = self.client.post(self.URL, data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Confirme a declaração de consentimento")
        self.assertContains(r, "Beto Lima")  # texto preservado para reenvio (dentro do JSON do config)
        self.assertEqual(Voter.objects.count(), 0)

    def test_duplicates_in_campaign_are_skipped_not_overwritten(self):
        existing = make_voter(self.a, self.cabo2, name="Nome Original", phone="5511999990001")
        self.login(self.admin)
        self.post()
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Nome Original")
        self.assertEqual(existing.registered_by_id, self.cabo2.pk)
        self.assertEqual(Voter.objects.filter(phone="5511999990001").count(), 1)
        self.assertEqual(Voter.objects.count(), 2)  # existente + Beto

    def test_server_ignores_client_preview_and_revalidates(self):
        self.login(self.cabo1)
        # o cliente "garante" um mapeamento que não cobre telefone: o servidor recusa
        r = self.post({"mapping": json.dumps(["nome", "", "bairro", ""])})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Associe as colunas obrigatórias")
        self.assertEqual(Voter.objects.count(), 0)
        for bad in ("{", json.dumps(["nome", "campo_falso", "", ""]), json.dumps(["nome", "nome", "", ""]), json.dumps("telefone")):
            r = self.post({"mapping": bad})
            self.assertEqual(r.status_code, 200)
        self.assertEqual(Voter.objects.count(), 0)

    def test_nothing_new_to_import(self):
        make_voter(self.a, self.cabo1, phone="5511999990001")
        make_voter(self.a, self.cabo1, phone="5511999990002")
        self.login(self.cabo1)
        r = self.post({"csv_text": "nome;telefone\nAna Souza;11999990001\nBeto Lima;11999990002\n", "mapping": json.dumps(["nome", "telefone"])})
        self.assertContains(r, "Nenhum eleitor novo para importar")
        self.assertFalse(AuditLog.objects.filter(action="voter.import").exists())

    def test_row_limit(self):
        rows = "\n".join(f"Pessoa {i:05d};119{90000000 + i}" for i in range(5001))
        self.login(self.admin)
        r = self.post({"csv_text": "nome;telefone\n" + rows, "mapping": json.dumps(["nome", "telefone"])})
        self.assertContains(r, "linhas demais")
        self.assertEqual(Voter.objects.count(), 0)

    def test_import_5000_rows(self):
        rows = "\n".join(f"Pessoa {i:05d};119{90000000 + i}" for i in range(5000))
        self.login(self.admin)
        r = self.post({"csv_text": "nome;telefone\n" + rows, "mapping": json.dumps(["nome", "telefone"])})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Voter.objects.filter(campaign=self.a).count(), 5000)

    def test_registered_by_must_be_in_scope(self):
        self.login(self.coord1)
        r = self.post({"registered_by": self.cabo2.pk})  # fora da rede do coordenador
        self.assertEqual(r.status_code, 200)
        r = self.post({"registered_by": self.admin_b.pk})  # outra campanha
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Voter.objects.count(), 0)
        r = self.post({"registered_by": self.cabo1.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(set(Voter.objects.values_list("registered_by_id", flat=True)), {self.cabo1.pk})

    def test_cabo_cannot_choose_registered_by(self):
        self.login(self.cabo1)
        self.post({"registered_by": self.cabo2.pk})
        self.assertEqual(set(Voter.objects.values_list("registered_by_id", flat=True)), {self.cabo1.pk})

    def test_inactive_member_cannot_be_chosen(self):
        inactive = make_user(self.a, "off@a.com", Role.CABO, parent=self.coord1, is_active=False)
        self.login(self.admin)
        self.assertEqual(self.post({"registered_by": inactive.pk}).status_code, 200)
        self.assertEqual(Voter.objects.count(), 0)

    def test_import_requires_csrf(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        r = strict.post(self.URL, {"csv_text": self.CSV, "declaration": "on"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Voter.objects.count(), 0)

    def test_sample_for_download_is_importable(self):
        from apps.voters.csv_import import SAMPLE_COLUMNS, SAMPLE_ROW

        text = ";".join(SAMPLE_COLUMNS) + "\n" + ";".join(SAMPLE_ROW)
        a = analyze_import(text, self.a.pk, today=TODAY)
        self.assertEqual(len(a.to_import), 1)
        self.assertEqual(a.results[0].warnings, [])
