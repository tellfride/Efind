"""Lógica pura (sem banco): cor, logo, diff de campos, filtros e rótulos da auditoria, formulários."""

import datetime as dt

from django.test import SimpleTestCase

from apps.core.constants import DEFAULT_CONSENT_TEXT
from apps.portal import audit_rules as ar
from apps.portal import settings_rules as sr
from apps.portal.forms import IdentityForm, PublicFormSettingsForm

from .helpers import data_url, identity_payload, jpeg_bytes, png_bytes, public_form_payload, webp_bytes


class ColorTests(SimpleTestCase):
    def test_hex_validation(self):
        for ok in ("#4f46e5", "#ABCDEF", "#000000"):
            self.assertTrue(sr.is_hex_color(ok), ok)
        for bad in ("4f46e5", "#4f46e", "#4f46e55", "#gggggg", "", None, 123, "#4f46e5 ", "rgb(0,0,0)"):
            self.assertFalse(sr.is_hex_color(bad), bad)

    def test_normalize(self):
        self.assertEqual(sr.normalize_hex_color(" #ABCDEF "), "#abcdef")
        self.assertIsNone(sr.normalize_hex_color("#abc"))
        self.assertIsNone(sr.normalize_hex_color(None))

    def test_readable_text_color(self):
        self.assertEqual(sr.readable_text_color("#000000"), "#ffffff")
        self.assertEqual(sr.readable_text_color("#ffffff"), "#0f172a")
        self.assertEqual(sr.readable_text_color("#facc15"), "#0f172a")  # amarelo claro
        self.assertEqual(sr.readable_text_color("#4f46e5"), "#ffffff")  # cor padrão da marca
        self.assertEqual(sr.readable_text_color("inválida"), "#ffffff")  # cai na cor padrão


class LogoValidationTests(SimpleTestCase):
    def test_accepts_png_jpeg_webp(self):
        self.assertEqual(sr.check_logo_data_url(data_url(png_bytes(), "image/png"))[0], "image/png")
        self.assertEqual(sr.check_logo_data_url(data_url(jpeg_bytes(), "image/jpeg"))[0], "image/jpeg")
        self.assertEqual(sr.check_logo_data_url(data_url(webp_bytes(), "image/webp"))[0], "image/webp")

    def test_reports_decoded_size(self):
        raw = png_bytes(4, 4)
        self.assertEqual(sr.check_logo_data_url(data_url(raw)), ("image/png", len(raw)))

    def test_rejects_wrong_mime_and_prefix(self):
        encoded = data_url(png_bytes()).split(",", 1)[1]
        for bad in (
            "data:image/gif;base64," + encoded,
            "data:image/svg+xml;base64," + encoded,
            "data:text/html;base64," + encoded,
            "data:image/png;charset=utf-8;base64," + encoded,
            "image/png;base64," + encoded,
            "https://exemplo.com/logo.png",
            "javascript:alert(1)",
            "",
        ):
            with self.assertRaises(sr.LogoError, msg=bad[:40]):
                sr.check_logo_data_url(bad)

    def test_rejects_bad_base64(self):
        for bad in ("data:image/png;base64,@@@@", "data:image/png;base64,abc", "data:image/png;base64,"):
            with self.assertRaises(sr.LogoError):
                sr.check_logo_data_url(bad)

    def test_rejects_non_strict_base64(self):
        valid = data_url(png_bytes())
        with self.assertRaises(sr.LogoError):  # espaço/quebra de linha dentro do base64
            sr.check_logo_data_url(valid[:40] + "\n" + valid[40:])

    def test_signature_must_match_declared_type(self):
        with self.assertRaises(sr.LogoError):
            sr.check_logo_data_url(data_url(b"<svg onload=alert(1)>" * 4, "image/png"))
        with self.assertRaises(sr.LogoError):  # PNG declarado como JPEG
            sr.check_logo_data_url(data_url(png_bytes(), "image/jpeg"))

    def test_size_limit(self):
        big = png_bytes() + b"\x00" * sr.LOGO_MAX_BYTES  # > 300 KB decodificado
        with self.assertRaisesMessage(sr.LogoError, "300 KB"):
            sr.check_logo_data_url(data_url(big))
        at_limit = png_bytes() + b"\x00" * (sr.LOGO_MAX_BYTES - len(png_bytes()))
        self.assertEqual(len(at_limit), sr.LOGO_MAX_BYTES)
        self.assertEqual(sr.check_logo_data_url(data_url(at_limit))[1], sr.LOGO_MAX_BYTES)
        with self.assertRaises(sr.LogoError):
            sr.check_logo_data_url(data_url(at_limit + b"\x00"))

    def test_dimension_limit(self):
        with self.assertRaises(sr.LogoError):
            sr.check_logo_data_url(data_url(png_bytes(sr.LOGO_MAX_SERVER_DIMENSION + 1, 1)))

    def test_image_dimensions(self):
        self.assertEqual(sr.image_dimensions("png", png_bytes(30, 20)), (30, 20))
        self.assertEqual(sr.image_dimensions("jpeg", jpeg_bytes(30, 20)), (30, 20))
        self.assertEqual(sr.image_dimensions("webp", webp_bytes(30, 20)), (30, 20))

    def test_is_safe_logo_url(self):
        self.assertTrue(sr.is_safe_logo_url(data_url(png_bytes())))
        self.assertFalse(sr.is_safe_logo_url(""))
        self.assertFalse(sr.is_safe_logo_url("javascript:alert(1)"))
        self.assertFalse(sr.is_safe_logo_url("data:image/svg+xml;base64,PHN2Zz4="))
        self.assertFalse(sr.is_safe_logo_url(None))


class ChangedFieldsTests(SimpleTestCase):
    def test_only_names_of_changed_fields(self):
        previous = {"a": "x", "b": "y", "c": None, "d": {"k": 1, "j": 2}}
        new = {"a": "x", "b": "z", "c": "", "d": {"j": 2, "k": 1}}
        self.assertEqual(sr.changed_fields(previous, new), ["b"])

    def test_none_and_empty_are_equivalent(self):
        self.assertEqual(sr.changed_fields({"a": None}, {"a": ""}), [])
        self.assertEqual(sr.changed_fields({"a": ""}, {"a": "novo"}), ["a"])

    def test_detects_nested_change_and_missing_key(self):
        self.assertEqual(sr.changed_fields({"cfg": {"email": "optional"}}, {"cfg": {"email": "required"}}), ["cfg"])
        self.assertEqual(sr.changed_fields({}, {"x": 1}), ["x"])

    def test_values_never_returned(self):
        names = sr.changed_fields({"logo_url": "AAA"}, {"logo_url": "BBBBBB" * 1000})
        self.assertEqual(names, ["logo_url"])


class IdentityFormTests(SimpleTestCase):
    def valid(self, **overrides):
        return IdentityForm(identity_payload(**overrides))

    def test_valid_payload(self):
        form = self.valid()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["primary_color"], "#112233")

    def test_color_is_normalized_to_lowercase(self):
        form = self.valid(primary_color="#AABBCC")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["primary_color"], "#aabbcc")

    def test_invalid_colors(self):
        for bad in ("112233", "#12345", "#1234567", "#12345g", "red", "#11 233", ""):
            form = self.valid(primary_color=bad)
            self.assertFalse(form.is_valid(), bad)
            self.assertIn("primary_color", form.errors)

    def test_ballot_number_digits_only(self):
        self.assertFalse(self.valid(ballot_number="12a").is_valid())
        self.assertFalse(self.valid(ballot_number="1").is_valid())
        self.assertFalse(self.valid(ballot_number="123456").is_valid())
        self.assertTrue(self.valid(ballot_number="").is_valid())

    def test_required_and_choice_fields(self):
        self.assertFalse(self.valid(candidate_name="").is_valid())
        self.assertFalse(self.valid(office="PRESIDENTE_DO_MUNDO").is_valid())
        self.assertFalse(self.valid(state="XX").is_valid())
        self.assertFalse(self.valid(election_year="1990").is_valid())
        self.assertFalse(self.valid(voter_goal="0").is_valid())
        self.assertTrue(self.valid(voter_goal="").is_valid())

    def test_logo_replace_requires_valid_data_url(self):
        ok = self.valid(logo_action="replace", logo_data=data_url(png_bytes()))
        self.assertTrue(ok.is_valid(), ok.errors)
        for bad in ("", "data:image/gif;base64,R0lGODlhAQABAAAAACw=", data_url(png_bytes(), "image/jpeg")):
            form = self.valid(logo_action="replace", logo_data=bad)
            self.assertFalse(form.is_valid())
            self.assertIn("logo_data", form.errors)

    def test_logo_too_big_is_rejected_by_field_or_check(self):
        big = data_url(png_bytes() + b"\x00" * (400 * 1024))
        form = self.valid(logo_action="replace", logo_data=big)
        self.assertFalse(form.is_valid())
        self.assertIn("logo_data", form.errors)
        self.assertIn("300 KB", form.errors["logo_data"][0])

    def test_logo_data_ignored_without_replace_action(self):
        form = self.valid(logo_action="keep", logo_data=data_url(png_bytes()))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["logo_data"], "")

    def test_invalid_logo_action_is_rejected(self):
        self.assertFalse(self.valid(logo_action="apagar-tudo").is_valid())


class PublicFormSettingsFormTests(SimpleTestCase):
    def valid(self, **overrides):
        return PublicFormSettingsForm(public_form_payload(**overrides))

    def test_valid_payload_and_config_keys(self):
        form = self.valid()
        self.assertTrue(form.is_valid(), form.errors)
        values = form.campaign_values()
        self.assertEqual(
            values["form_config"],
            {"email": "optional", "birth_date": "hidden", "gender": "optional", "address": "required", "electoral": "hidden"},
        )

    def test_invalid_mode_rejected(self):
        for field in ("config_email", "config_birth_date", "config_gender", "config_address", "config_electoral"):
            self.assertFalse(self.valid(**{field: "obrigatorio"}).is_valid(), field)

    def test_missing_mode_rejected(self):
        data = public_form_payload()
        del data["config_gender"]
        self.assertFalse(PublicFormSettingsForm(data).is_valid())

    def test_consent_text_rules(self):
        empty = self.valid(consent_text="")
        self.assertTrue(empty.is_valid(), empty.errors)
        self.assertEqual(empty.cleaned_data["consent_text"], "")
        short = self.valid(consent_text="curto demais")
        self.assertFalse(short.is_valid())
        self.assertIn("consent_text", short.errors)
        text = "Autorizo {{candidato}} a usar meus dados para comunicação política conforme a LGPD."
        long_form = self.valid(consent_text=text)
        self.assertTrue(long_form.is_valid(), long_form.errors)
        self.assertEqual(long_form.cleaned_data["consent_text"], text)

    def test_default_consent_text_is_stored_as_empty(self):
        form = self.valid(consent_text=DEFAULT_CONSENT_TEXT)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["consent_text"], "")

    def test_length_limits(self):
        self.assertFalse(self.valid(form_message="x" * (sr.LIMITS["form_message"] + 1)).is_valid())
        self.assertFalse(self.valid(form_title="x" * (sr.LIMITS["form_title"] + 1)).is_valid())
        self.assertFalse(self.valid(consent_text="x" * (sr.LIMITS["consent_text_max"] + 1)).is_valid())

    def test_mode_rows_follow_groups(self):
        form = PublicFormSettingsForm(initial={})
        self.assertEqual([row["key"] for row in form.mode_rows()], ["email", "birth_date", "gender", "address", "electoral"])


class AuditFilterTests(SimpleTestCase):
    USER = "5f1c9a9e-3f5b-4a44-9e62-1d3b0f7c6a10"
    OTHER = "0b9d3c5e-92a4-4b4d-8f58-3a2e6b1f9c11"

    def test_empty(self):
        filters = ar.parse_audit_filters({})
        self.assertFalse(filters.active)
        self.assertEqual(filters.to_params(), {})

    def test_valid_values(self):
        filters = ar.parse_audit_filters(
            {"user": self.USER, "action": "voter.export", "from": "2026-01-10", "to": "2026-02-01"},
            allowed_user_ids={self.USER},
            allowed_actions={"voter.export"},
        )
        self.assertTrue(filters.active)
        self.assertEqual(filters.user_id, self.USER)
        self.assertEqual(filters.action, "voter.export")
        self.assertEqual(filters.date_from, dt.date(2026, 1, 10))
        self.assertEqual(filters.date_to, dt.date(2026, 2, 1))
        self.assertEqual(filters.to_params(), {"user": self.USER, "action": "voter.export", "from": "2026-01-10", "to": "2026-02-01"})

    def test_user_outside_allowed_list_is_dropped(self):
        filters = ar.parse_audit_filters({"user": self.OTHER}, allowed_user_ids={self.USER})
        self.assertIsNone(filters.user_id)

    def test_malformed_values_are_dropped(self):
        filters = ar.parse_audit_filters(
            {"user": "não-é-uuid", "action": "voter.export; DROP TABLE x", "from": "10/01/2026", "to": "2026-13-45"}
        )
        self.assertFalse(filters.active)

    def test_unknown_action_is_dropped_when_list_given(self):
        self.assertIsNone(ar.parse_audit_filters({"action": "foo.bar"}, allowed_actions={"voter.export"}).action)

    def test_swapped_dates_are_reordered(self):
        filters = ar.parse_audit_filters({"from": "2026-05-10", "to": "2026-05-01"})
        self.assertEqual((filters.date_from, filters.date_to), (dt.date(2026, 5, 1), dt.date(2026, 5, 10)))

    def test_year_bounds(self):
        self.assertIsNone(ar.parse_iso_date("1999-12-31"))
        self.assertIsNone(ar.parse_iso_date("2101-01-01"))
        self.assertEqual(ar.parse_iso_date("2026-02-28"), dt.date(2026, 2, 28))
        self.assertIsNone(ar.parse_iso_date("2026-02-30"))

    def test_list_values_use_first_item(self):
        self.assertEqual(ar.parse_audit_filters({"action": ["voter.export", "x"]}).action, "voter.export")

    def test_created_range_uses_sao_paulo_day_bounds(self):
        filters = ar.parse_audit_filters({"from": "2026-03-01", "to": "2026-03-01"})
        start, end = ar.created_range(filters)
        self.assertEqual(start.isoformat(), "2026-03-01T00:00:00-03:00")
        self.assertEqual(end.isoformat(), "2026-03-02T00:00:00-03:00")
        self.assertEqual(ar.created_range(ar.AuditFilters()), (None, None))


class AuditLabelTests(SimpleTestCase):
    def test_known_and_unknown_actions(self):
        self.assertEqual(ar.audit_action_label("settings.update"), "Configurações atualizadas")
        self.assertEqual(ar.audit_action_label("audit.export"), "Auditoria exportada")
        self.assertEqual(ar.audit_action_label("voter.merge_all"), "Eleitores: merge all")
        self.assertEqual(ar.audit_action_label("estranha"), "estranha")

    def test_grouping_is_sorted_and_deduplicated(self):
        groups = ar.group_audit_actions(["voter.export", "voter.create", "voter.export", "settings.update", "xyz.a"])
        self.assertEqual([g["label"] for g in groups], ["Configurações", "Eleitores", "Outras"])
        voter = next(g for g in groups if g["label"] == "Eleitores")
        self.assertEqual([value for value, _ in voter["options"]], ["voter.create", "voter.export"])

    def test_entity_label(self):
        self.assertEqual(ar.audit_entity_label("Voter"), "Eleitor")
        self.assertEqual(ar.audit_entity_label("Campaign"), "Campanha")
        self.assertEqual(ar.audit_entity_label("Outra"), "Outra")
        self.assertEqual(ar.audit_entity_label(""), "")

    def test_format_details(self):
        self.assertIsNone(ar.format_audit_details(None))
        self.assertIsNone(ar.format_audit_details({}))
        pretty = ar.format_audit_details({"b": 1, "a": "ç"})
        self.assertIn('"a": "ç"', pretty)
        self.assertLess(pretty.index('"a"'), pretty.index('"b"'))

    def test_export_filename(self):
        today = dt.date(2026, 10, 10)
        self.assertEqual(ar.export_filename(ar.AuditFilters(), today), "auditoria_2026-10-10.csv")
        name = ar.export_filename(ar.AuditFilters(date_from=dt.date(2026, 1, 1)), today)
        self.assertEqual(name, "auditoria_2026-10-10_2026-01-01_a_hoje.csv")
        name = ar.export_filename(ar.AuditFilters(date_from=dt.date(2026, 1, 1), date_to=dt.date(2026, 1, 31)), today)
        self.assertEqual(name, "auditoria_2026-10-10_2026-01-01_a_2026-01-31.csv")
