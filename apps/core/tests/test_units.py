from django.test import SimpleTestCase, override_settings

from apps.core import crypto
from apps.core.constants import Role, parse_form_config
from apps.core.permissions import can, default_permissions_for, resolve_permissions
from apps.core.phone import format_phone, normalize_br_phone, whatsapp_link
from apps.core.template_vars import extract_variables, render_template, unknown_variables
from apps.core.utils import age_from, parse_tags, serialize_tags, title_case, to_csv
from apps.core.voter_filters import parse_voter_filters, sanitize_voter_filters, voter_filters_to_params


def row(module, **values):
    base = {"module": module, "can_view": None, "can_create": None, "can_edit": None, "can_delete": None, "can_export": None}
    return {**base, **values}


class PermissionTests(SimpleTestCase):
    def test_admin_has_everything_super_admin_nothing(self):
        admin = resolve_permissions(Role.ADMIN)
        self.assertTrue(can(admin, "whatsapp", "edit"))
        self.assertFalse(can(admin, "mapa", "delete"))  # ação não suportada pelo módulo
        self.assertFalse(can(resolve_permissions(Role.SUPER_ADMIN), "eleitores", "view"))

    def test_default_then_role_then_user_override(self):
        self.assertFalse(can(default_permissions_for(Role.CABO), "eleitores", "export"))
        perms = resolve_permissions(
            Role.CABO, [row("eleitores", can_export=True)], [row("eleitores", can_create=False)]
        )
        self.assertTrue(can(perms, "eleitores", "export"))
        self.assertFalse(can(perms, "eleitores", "create"))
        self.assertTrue(can(perms, "eleitores", "view"))

    def test_without_view_nothing_else_applies(self):
        perms = resolve_permissions(Role.COORDENADOR, [row("eleitores", can_view=False)])
        self.assertFalse(can(perms, "eleitores", "create"))
        self.assertFalse(can(perms, "eleitores", "export"))

    def test_unknown_module_rows_are_ignored(self):
        perms = resolve_permissions(Role.CABO, [row("inexistente", can_view=True)])
        self.assertNotIn("inexistente", perms)


class PhoneTests(SimpleTestCase):
    def test_normalizes_brazilian_formats(self):
        self.assertEqual(normalize_br_phone("(11) 98765-4321"), "5511987654321")
        self.assertEqual(normalize_br_phone("+55 19 3232-1234"), "551932321234")
        self.assertEqual(normalize_br_phone("011987654321"), "5511987654321")
        self.assertEqual(normalize_br_phone("5511987654321"), "5511987654321")

    def test_rejects_invalid(self):
        for bad in ["", None, "123", "(00) 98765-4321", "(11) 88765-4321", "+1 202 555 0100"]:
            self.assertIsNone(normalize_br_phone(bad), bad)

    def test_format_and_link(self):
        self.assertEqual(format_phone("5511987654321"), "(11) 98765-4321")
        self.assertEqual(format_phone("551932321234"), "(19) 3232-1234")
        self.assertEqual(whatsapp_link("5511987654321", "Olá!"), "https://wa.me/5511987654321?text=Ol%C3%A1%21")


class TemplateVarTests(SimpleTestCase):
    def test_render_is_case_and_space_tolerant(self):
        out = render_template("Oi {{ primeiro_nome }} do {{BAIRRO}} {{x}}!", {"primeiro_nome": "Ana", "bairro": "Centro"})
        self.assertEqual(out, "Oi Ana do Centro !")

    def test_extract_and_unknown(self):
        self.assertEqual(extract_variables("{{nome}} {{bairro}} {{nome}}"), ["nome", "bairro"])
        self.assertEqual(unknown_variables("{{nome}} {{foo}}"), ["foo"])


class VoterFilterTests(SimpleTestCase):
    def test_roundtrip_discards_invalid_values(self):
        from django.http import QueryDict

        qd = QueryDict("bairro=Centro&bairro=Cambuí&genero=F&idade_min=18&whatsapp=1&de=2026-01-01&ate=errado&cabo=nao-uuid")
        f = parse_voter_filters(qd)
        self.assertEqual(
            f,
            {"neighborhoods": ["Centro", "Cambuí"], "genders": ["F"], "age_min": 18, "messageable": True, "created_from": "2026-01-01"},
        )
        again = parse_voter_filters(QueryDict("&".join(f"{k}={v}" for k, v in voter_filters_to_params(f))))
        self.assertEqual(again, f)

    def test_sanitize_rejects_unknown_enum_values(self):
        self.assertEqual(sanitize_voter_filters({"genders": ["Z"], "sources": ["LINK", "X"]}), {"sources": ["LINK"]})


class UtilTests(SimpleTestCase):
    def test_tags_and_names(self):
        self.assertEqual(serialize_tags("Saúde, jovem ,saude"), ",saude,jovem,")
        self.assertEqual(parse_tags(",saude,jovem,"), ["saude", "jovem"])
        self.assertEqual(title_case("MARIA DA SILVA"), "Maria da Silva")

    def test_title_case_capitalizes_after_apostrophe_and_hyphen(self):
        # Regressão (QA no navegador): "joão d'ávila da silva" virava "João D'ávila da Silva"
        self.assertEqual(title_case("joão d'ávila da silva"), "João D'Ávila da Silva")
        self.assertEqual(title_case("MARIA DALL'AGNOL"), "Maria Dall'Agnol")
        self.assertEqual(title_case("ana-clara dos santos"), "Ana-Clara dos Santos")
        self.assertEqual(title_case("sant’anna"), "Sant’Anna")  # apóstrofo tipográfico (colado do Word/WhatsApp)
        self.assertEqual(title_case("  josé   da  silva  "), "José da Silva")
        self.assertEqual(title_case("d'"), "D'")  # sem letra depois do apóstrofo
        self.assertEqual(title_case(""), "")

    def test_csv_blocks_formula_injection(self):
        csv_text = to_csv([{"a": "=1+1", "b": 'x"y'}], [("a", "A"), ("b", "B")])
        self.assertIn("'=1+1", csv_text)
        self.assertIn('"x""y"', csv_text)
        self.assertTrue(csv_text.startswith("﻿"))

    def test_age(self):
        import datetime as dt

        self.assertEqual(age_from(dt.date(2000, 6, 15), dt.date(2026, 6, 14)), 25)
        self.assertEqual(age_from(dt.date(2000, 6, 15), dt.date(2026, 6, 15)), 26)

    def test_form_config_defaults_and_validation(self):
        cfg = parse_form_config({"email": "required", "gender": "bogus"})
        self.assertEqual(cfg["email"], "required")
        self.assertEqual(cfg["gender"], "optional")


@override_settings(ENCRYPTION_KEY="BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=")
class CryptoTests(SimpleTestCase):
    def test_roundtrip_and_tamper_detection(self):
        payload = crypto.encrypt_json({"token": "segredo"})
        self.assertTrue(payload.startswith("v1:"))
        self.assertEqual(crypto.decrypt_json(payload), {"token": "segredo"})
        tampered = payload[:-4] + ("AAAA" if not payload.endswith("AAAA") else "BBBB")
        with self.assertRaises(Exception):
            crypto.decrypt_string(tampered)

    def test_mask_secret(self):
        self.assertEqual(crypto.mask_secret("EAAGabcdefghijklmnop9xZw"), "EAAG••••••9xZw")
        self.assertEqual(crypto.mask_secret(""), "")
