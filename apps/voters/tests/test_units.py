"""Lógica pura: utilitários, formulários (schema e normalização), regra de recadastro e exportação."""

import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.core.constants import DEFAULT_FORM_CONFIG
from apps.core.utils import to_csv
from apps.voters.export import EXPORT_COLUMNS, audit_safe_filters, voter_to_export_row
from apps.voters.forms import (
    PANEL_FORM_CONFIG,
    PublicRegistrationForm,
    VoterDataForm,
    voter_data_from_cleaned,
)
from apps.voters.merge import geo_address_changed, plan_duplicate_merge
from apps.voters.utils import (
    brand_css_vars,
    is_hex_color,
    is_valid_invite_code,
    mix_hex,
    parse_birth_date_input,
    parse_voter_sort,
    readable_text_color,
    safe_hex_color,
    safe_ip,
    safe_logo_url,
    scalable_svg,
    short_url,
    smart_case,
    sort_expressions,
    whatsapp_share_url,
    whatsapp_status_of,
)

NOW = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.UTC)


class UtilsTests(SimpleTestCase):
    def test_invite_code(self):
        self.assertTrue(is_valid_invite_code("AbC123xy"))
        for bad in (None, "", "ab", "a" * 33, "abc-123", "../../etc", "abc 123"):
            self.assertFalse(is_valid_invite_code(bad), bad)

    def test_birth_date_formats(self):
        d = dt.date(1985, 3, 15)
        for raw in ("15/03/1985", "15-03-1985", "15.03.1985", "15031985", "1985-03-15", " 1985-03-15T00:00:00 ", "15/3/1985"):
            self.assertEqual(parse_birth_date_input(raw), d, raw)
        for bad in ("", None, "31/02/1990", "15/13/1990", "99/99/9999", "01/01/1700", "abc", "1985/03/15"):
            self.assertIsNone(parse_birth_date_input(bad), bad)

    def test_smart_case(self):
        self.assertEqual(smart_case("  AVENIDA   PAULISTA "), "Avenida Paulista")
        self.assertEqual(smart_case("rua das flores"), "Rua das Flores")
        self.assertEqual(smart_case("Rua XV de Novembro"), "Rua XV de Novembro")  # misto: preserva
        self.assertEqual(smart_case(None), "")

    def test_colors_are_validated(self):
        self.assertTrue(is_hex_color("#fff"))
        self.assertTrue(is_hex_color("#E11D48"))
        for bad in ("red", "#12", "#12345g", "url(x)", "#fff;background:x", "", None):
            self.assertFalse(is_hex_color(bad), bad)
        self.assertEqual(safe_hex_color("#ABC"), "#aabbcc")
        self.assertEqual(safe_hex_color("javascript:1"), "#4f46e5")
        self.assertEqual(safe_hex_color(None, "#000000"), "#000000")
        self.assertEqual(readable_text_color("#ffffff"), "#0f172a")
        self.assertEqual(readable_text_color("#1e1b4b"), "#ffffff")
        self.assertEqual(mix_hex("#000000", "#ffffff", 0.5), "#808080")
        self.assertTrue(all(v.startswith("#") and len(v) == 7 for v in brand_css_vars("#e11d48").values()))

    def test_logo_url_whitelist(self):
        self.assertEqual(safe_logo_url("https://x.com/a.png"), "https://x.com/a.png")
        self.assertEqual(safe_logo_url("/static/img/a.png"), "/static/img/a.png")
        self.assertTrue(safe_logo_url("data:image/png;base64,iVBORw0KGgo="))
        for bad in ("javascript:alert(1)", "data:image/svg+xml;base64,PHN2Zz4=", "//evil.com/a.png", 'https://x.com/a.png"onerror="x', "", None):
            self.assertEqual(safe_logo_url(bad), "", bad)

    def test_whatsapp_helpers(self):
        self.assertEqual(whatsapp_share_url("Olá, tudo bem? https://x/c/a/"), "https://wa.me/?text=Ol%C3%A1%2C%20tudo%20bem%3F%20https%3A%2F%2Fx%2Fc%2Fa%2F")
        self.assertEqual(short_url("https://efind.com.br/c/abc/"), "efind.com.br/c/abc")
        self.assertEqual(short_url("http://localhost:8000/c/abc/?src=qr"), "localhost:8000/c/abc/?src=qr")

    def test_safe_ip(self):
        self.assertEqual(safe_ip("203.0.113.9"), "203.0.113.9")
        self.assertEqual(safe_ip("::1"), "::1")
        for bad in ("", None, "lixo", "999.1.1.1"):
            self.assertIsNone(safe_ip(bad))

    def test_scalable_svg(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="330" height="330" class="x"><g/></svg>'
        out = scalable_svg(svg)
        self.assertIn('viewBox="0 0 330 330"', out)
        self.assertNotIn('width="330"', out)

    def test_sort(self):
        self.assertEqual(parse_voter_sort("nome"), "nome")
        self.assertEqual(parse_voter_sort("x; drop"), "recentes")
        self.assertEqual(parse_voter_sort(None), "recentes")
        self.assertEqual(sort_expressions("antigos"), ("created_at", "pk"))
        self.assertEqual(sort_expressions("recentes"), ("-created_at", "pk"))

    def test_whatsapp_status(self):
        base = dict(opt_out_at=None, whatsapp_opt_in=True, consent_at=NOW)
        self.assertEqual(whatsapp_status_of(SimpleNamespace(**base)), "APTO")
        self.assertEqual(whatsapp_status_of(SimpleNamespace(**{**base, "opt_out_at": NOW})), "DESCADASTRADO")
        self.assertEqual(whatsapp_status_of(SimpleNamespace(**{**base, "whatsapp_opt_in": False})), "SEM_AUTORIZACAO")
        self.assertEqual(whatsapp_status_of(SimpleNamespace(**{**base, "consent_at": None})), "SEM_AUTORIZACAO")


VALID_PUBLIC = {
    "name": "  MARIA   da silva ",
    "phone": "(11) 98765-4321",
    "cep": "01310-100",
    "street": "AVENIDA PAULISTA",
    "number": "1000",
    "neighborhood": "bela vista",
    "city": "SÃO PAULO",
    "state": "SP",
    "consent": "on",
}


class PublicFormSchemaTests(SimpleTestCase):
    def form(self, data=None, config=None):
        return PublicRegistrationForm(data, config=config)

    def test_default_schema(self):
        f = self.form()
        self.assertEqual(
            set(f.fields),
            {"name", "phone", "email", "birth_date", "gender", "cep", "street", "number", "complement", "neighborhood", "city", "state", "consent", "whatsapp_opt_in", "source", "website"},
        )
        self.assertTrue(f.fields["name"].required)
        self.assertTrue(f.fields["phone"].required)
        self.assertTrue(f.fields["cep"].required)  # padrão: endereço obrigatório
        self.assertFalse(f.fields["email"].required)
        self.assertTrue(f.fields["consent"].required)
        self.assertFalse(f.fields["whatsapp_opt_in"].required)
        self.assertEqual(f.fields["cep"].widget.attrs["data-mask"], "cep")
        self.assertIn("data-cep-lookup", f.fields["cep"].widget.attrs)
        self.assertIn("#id_street", f.fields["cep"].widget.attrs["data-cep-target"])
        self.assertEqual(f.fields["phone"].widget.attrs["data-mask"], "phone")

    def test_consents_start_unchecked(self):
        f = self.form()
        self.assertFalse(f["consent"].value())
        self.assertFalse(f["whatsapp_opt_in"].value())

    def test_config_hidden_optional_required(self):
        f = self.form(config={"email": "required", "birth_date": "hidden", "gender": "hidden", "address": "optional", "electoral": "required"})
        self.assertTrue(f.fields["email"].required)
        self.assertNotIn("birth_date", f.fields)
        self.assertNotIn("gender", f.fields)
        self.assertFalse(f.fields["cep"].required)
        self.assertTrue(f.fields["electoral_zone"].required)
        self.assertTrue(f.show_email and f.show_address and f.show_electoral)
        self.assertFalse(f.show_birth_date or f.show_gender)

    def test_hidden_address_removes_every_address_field(self):
        f = self.form(config={"address": "hidden"})
        for name in ("cep", "street", "number", "complement", "neighborhood", "city", "state"):
            self.assertNotIn(name, f.fields)

    def test_invalid_config_values_fall_back_to_defaults(self):
        f = self.form(config={"email": "obrigatorio", "address": 5, "x": "required"})
        self.assertFalse(f.fields["email"].required)
        self.assertEqual(f.config["address"], DEFAULT_FORM_CONFIG["address"])

    def test_panel_config_is_all_optional(self):
        f = VoterDataForm()
        self.assertEqual(f.config, PANEL_FORM_CONFIG)
        self.assertFalse(f.fields["cep"].required)
        self.assertTrue(f.fields["name"].required)


class PublicFormNormalizationTests(SimpleTestCase):
    def clean(self, **over):
        form = PublicRegistrationForm({**VALID_PUBLIC, **over})
        self.assertTrue(form.is_valid(), form.errors.as_json())
        return form.cleaned_data

    def test_normalizes_everything(self):
        c = self.clean(email=" MARIA@Exemplo.COM ", birth_date="15/03/1985", gender="F")
        self.assertEqual(c["name"], "Maria da Silva")
        self.assertEqual(c["phone"], "5511987654321")
        self.assertEqual(c["cep"], "01310100")
        self.assertEqual(c["street"], "Avenida Paulista")
        self.assertEqual(c["neighborhood"], "Bela Vista")
        self.assertEqual(c["city"], "São Paulo")
        self.assertEqual(c["email"], "maria@exemplo.com")
        self.assertEqual(c["birth_date"], dt.date(1985, 3, 15))
        data = voter_data_from_cleaned(c)
        self.assertEqual(data["phone"], "5511987654321")
        self.assertEqual(data["complement"], "")

    def test_phone_variants(self):
        for raw in ("11987654321", "+55 11 98765-4321", "011 98765 4321", "5511987654321"):
            self.assertEqual(self.clean(phone=raw)["phone"], "5511987654321", raw)

    def test_invalid_values(self):
        cases = {
            "phone": ["123", "11 12345-6789", "(00) 98765-4321", "abc"],
            "name": ["Jo", "  ", "1234"],
            "cep": ["123", "00000000", "abcde-fgh"],
            "email": ["sem-arroba", "a@b"],
            "state": ["XX"],
        }
        for field, values in cases.items():
            for value in values:
                form = PublicRegistrationForm({**VALID_PUBLIC, field: value})
                self.assertFalse(form.is_valid(), (field, value))
                self.assertIn(field, form.errors, (field, value))

    def test_required_missing(self):
        form = PublicRegistrationForm({"name": "", "phone": "", "consent": ""})
        self.assertFalse(form.is_valid())
        for field in ("name", "phone", "cep", "street", "number", "neighborhood", "city", "state", "consent"):
            self.assertIn(field, form.errors, field)

    def test_birth_date_age_limits(self):
        today = dt.date.today()
        too_young = today.replace(year=today.year - 10).strftime("%d/%m/%Y")
        too_old = today.replace(year=today.year - 130).strftime("%d/%m/%Y")
        for raw in (too_young, too_old):
            form = PublicRegistrationForm({**VALID_PUBLIC, "birth_date": raw})
            self.assertIn("birth_date", form.errors, raw)
        ok16 = today.replace(year=today.year - 16).strftime("%d/%m/%Y")
        self.assertTrue(PublicRegistrationForm({**VALID_PUBLIC, "birth_date": ok16}).is_valid())

    def test_electoral_fields(self):
        f = PublicRegistrationForm({**VALID_PUBLIC, "electoral_zone": "0025", "electoral_section": "00120"}, config={"electoral": "optional"})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual((f.cleaned_data["electoral_zone"], f.cleaned_data["electoral_section"]), ("25", "120"))
        f = PublicRegistrationForm({**VALID_PUBLIC, "electoral_zone": "12345"}, config={"electoral": "optional"})
        self.assertIn("electoral_zone", f.errors)

    def test_source_whitelist(self):
        self.assertEqual(self.clean(source="qrcode")["source"], "QRCODE")
        self.assertEqual(self.clean(source="LINK")["source"], "LINK")
        self.assertEqual(self.clean(source="IMPORT")["source"], "LINK")
        self.assertEqual(self.clean()["source"], "LINK")

    def test_hidden_fields_are_dropped_from_data(self):
        form = PublicRegistrationForm({**VALID_PUBLIC, "email": "x@y.com"}, config={"email": "hidden", "address": "hidden"})
        self.assertTrue(form.is_valid(), form.errors)
        data = voter_data_from_cleaned(form.cleaned_data)
        self.assertEqual((data["email"], data["cep"], data["city"]), ("", "", ""))


class MergeTests(SimpleTestCase):
    def existing(self, **over):
        base = dict(email="", birth_date=None, gender="", cep="", street="", number="", complement="", neighborhood="", city="", state="", electoral_zone="", electoral_section="")
        return SimpleNamespace(**{**base, **over})

    def plan(self, existing, incoming, **over):
        kwargs = dict(whatsapp_opt_in=False, consent_text="texto", consent_ip="203.0.113.9", now=NOW)
        return plan_duplicate_merge(existing, incoming, **{**kwargs, **over})

    def test_renews_consent_and_fills_only_empty_fields(self):
        existing = self.existing(neighborhood="Centro", email="velho@x.com")
        plan = self.plan(existing, {"neighborhood": "Outro", "email": "novo@x.com", "city": "Campinas", "state": "SP"})
        u = plan.updates
        self.assertEqual((u["consent_at"], u["consent_ip"], u["consent_text"]), (NOW, "203.0.113.9", "texto"))
        self.assertNotIn("neighborhood", u)
        self.assertNotIn("email", u)
        self.assertEqual((u["city"], u["state"]), ("Campinas", "SP"))
        self.assertEqual(sorted(plan.filled), ["city", "state"])
        self.assertTrue(plan.needs_geocode)
        self.assertEqual(u["geo_status"], "PENDING")
        self.assertNotIn("name", u)
        self.assertNotIn("registered_by", u)
        self.assertNotIn("registered_by_id", u)

    def test_whatsapp_changes_only_when_checked_now(self):
        plan = self.plan(self.existing(), {}, whatsapp_opt_in=False)
        self.assertNotIn("whatsapp_opt_in", plan.updates)
        self.assertNotIn("opt_out_at", plan.updates)
        plan = self.plan(self.existing(), {}, whatsapp_opt_in=True)
        self.assertIs(plan.updates["whatsapp_opt_in"], True)
        self.assertIsNone(plan.updates["opt_out_at"])

    def test_no_geocode_when_address_not_completed(self):
        plan = self.plan(self.existing(), {"email": "a@b.com", "number": "10"})
        self.assertFalse(plan.needs_geocode)
        self.assertNotIn("geo_status", plan.updates)

    def test_geo_address_changed_ignores_case_accents_and_number(self):
        before = SimpleNamespace(cep="01310100", street="Avenida Paulista", neighborhood="Bela Vista", city="São Paulo", state="SP")
        same = {"cep": "01310100", "street": "avenida  paulista", "neighborhood": "BELA VISTA", "city": "Sao Paulo", "state": "SP", "number": "9"}
        self.assertFalse(geo_address_changed(before, same))
        self.assertTrue(geo_address_changed(before, {**same, "neighborhood": "Jardins"}))
        self.assertTrue(geo_address_changed(before, {**same, "cep": ""}))


class ExportTests(TestCase):
    def voter(self, **over):
        from apps.core.constants import Role
        from apps.voters.models import Voter

        from .helpers import make_campaign, make_user

        campaign = make_campaign("export")
        user = make_user(campaign, "u@e.com", Role.ADMIN, name="Ana Admin")
        data = dict(
            campaign=campaign, registered_by=user, name="Maria da Silva", phone="5511987654321", email="m@x.com",
            birth_date=dt.date(1985, 3, 15), gender="F", cep="01310100", street="Avenida Paulista", number="1000",
            neighborhood="Bela Vista", city="São Paulo", state="SP", support_level="APOIADOR", tags=",saude,jovem,",
            source="QRCODE", whatsapp_opt_in=True, consent_at=NOW, notes="obs",
        )
        data.update(over)
        return Voter.objects.create(**data)

    def test_row_mapping(self):
        row = voter_to_export_row(self.voter(), today=dt.date(2026, 10, 10))
        self.assertEqual(row["nome"], "Maria da Silva")
        self.assertEqual(row["whatsapp"], "(11) 98765-4321")
        self.assertEqual(row["nascimento"], "15/03/1985")
        self.assertEqual(row["idade"], 41)
        self.assertEqual(row["genero"], "Feminino")
        self.assertEqual(row["cep"], "01310-100")
        self.assertEqual(row["apoio"], "Apoiador")
        self.assertEqual(row["tags"], "saude, jovem")
        self.assertEqual(row["origem"], "QR Code")
        self.assertEqual(row["cadastrado_por"], "Ana Admin")
        self.assertEqual(row["situacao_whatsapp"], "Apto a WhatsApp")
        self.assertEqual(row["consentimento"], "10/10/2026 09:00")  # UTC → America/Sao_Paulo
        self.assertEqual(set(row), {key for key, _ in EXPORT_COLUMNS})

    def test_csv_output_neutralizes_formulas(self):
        v = self.voter(name="=SOMA(A1)", email="@evil.com", notes="-2+3", street="+cmd", city="\tX")
        csv_text = to_csv([voter_to_export_row(v)], EXPORT_COLUMNS)
        self.assertTrue(csv_text.startswith("﻿"))
        lines = csv_text.split("\r\n")
        self.assertEqual(lines[0].split(";")[0].lstrip("﻿"), "Nome")
        data = lines[1]
        for dangerous in ("=SOMA", "@evil", "-2+3", "+cmd"):
            self.assertNotIn(";" + dangerous, data)
            self.assertFalse(data.startswith(dangerous))
        self.assertIn("'=SOMA(A1)", data)
        self.assertIn("'@evil.com", data)
        self.assertIn("'-2+3", data)

    def test_status_labels_for_opted_out_and_no_consent(self):
        self.assertEqual(voter_to_export_row(self.voter(opt_out_at=NOW))["situacao_whatsapp"], "Descadastrado")

    def test_audit_filters_hide_search_text(self):
        self.assertEqual(audit_safe_filters({"q": "maria 11987654321", "cities": ["Campinas"]}), {"q": "(busca por texto)", "cities": ["Campinas"]})
        self.assertEqual(audit_safe_filters({}), {})
