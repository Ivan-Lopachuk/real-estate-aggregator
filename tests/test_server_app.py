"""
Тести для server/app.py — лише чиста логіка (розбір відповіді AI,
побудова критеріїв, фільтр «за останні N днів»), без мережі й без
реального звернення до OpenRouter чи сайтів нерухомості.

server/ лежить поза пакетом aggregator/, тож імпортуємо його файл
напряму за шляхом — так само, як tests/test_apply_search_criteria.py
робить для scripts/apply_search_criteria.py.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from aggregator.models import Listing

_APP_PATH = Path(__file__).resolve().parent.parent / "server" / "app.py"
_spec = importlib.util.spec_from_file_location("chat_server_app", _APP_PATH)
chat_app = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = chat_app
_spec.loader.exec_module(chat_app)


class ExtractJsonTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(chat_app._extract_json('{"a": 1}'), {"a": 1})

    def test_json_with_surrounding_text(self):
        text = 'Ось відповідь:\n{"a": 1, "b": "x"}\nДякую.'
        self.assertEqual(chat_app._extract_json(text), {"a": 1, "b": "x"})

    def test_invalid_json_returns_none(self):
        self.assertIsNone(chat_app._extract_json("не json взагалі"))


class BuildCriteriaTests(unittest.TestCase):
    def test_defaults_to_rent_and_both_property_types(self):
        criteria = chat_app._build_criteria({}, ["9000"])
        self.assertEqual(criteria.transaction, "rent")
        self.assertEqual(criteria.property_types, ["house", "apartment"])
        self.assertEqual(criteria.postal_codes, ["9000"])

    def test_sale_and_single_property_type_are_respected(self):
        parsed = {"transaction": "sale", "property_types": ["apartment"], "price_max": 300000}
        criteria = chat_app._build_criteria(parsed, [])
        self.assertEqual(criteria.transaction, "sale")
        self.assertEqual(criteria.property_types, ["apartment"])
        self.assertEqual(criteria.price_max, 300000)


class ParseListedAtTests(unittest.TestCase):
    def test_parses_immoweb_style_with_milliseconds_and_z(self):
        dt = chat_app._parse_listed_at("2026-09-03T13:49:41.693Z")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 9)

    def test_parses_zimmo_style_with_offset(self):
        dt = chat_app._parse_listed_at("2026-08-01T07:54:11+00:00")
        self.assertIsNotNone(dt)

    def test_invalid_value_returns_none(self):
        self.assertIsNone(chat_app._parse_listed_at("не дата"))


class ApplyRecencyTests(unittest.TestCase):
    def test_keeps_recent_and_missing_dates_drops_old(self):
        recent = Listing(site="immoweb", site_listing_id="1", url="u1", title="t1",
                          listed_at="2026-09-03T13:49:41.693Z")
        old = Listing(site="zimmo", site_listing_id="2", url="u2", title="t2",
                       listed_at="2026-08-01T07:54:11+00:00")
        unknown = Listing(site="immoweb", site_listing_id="3", url="u3", title="t3", listed_at=None)

        kept = chat_app._apply_recency([recent, old, unknown], 2)
        self.assertEqual({l.uid for l in kept}, {"immoweb:1", "immoweb:3"})

    def test_no_days_back_keeps_everything(self):
        listings = [Listing(site="immoweb", site_listing_id="1", url="u1", title="t1")]
        self.assertEqual(chat_app._apply_recency(listings, None), listings)


class AccessOkTests(unittest.TestCase):
    def test_no_access_code_configured_denies_by_default(self):
        # ACCESS_CODE не задано в тестовому середовищі (нема env-змінної) —
        # доступ має бути закритий за замовчуванням, а не відкритий.
        chat_app.ACCESS_CODE = ""
        with chat_app.app.test_request_context(headers={"X-Access-Code": ""}):
            self.assertFalse(chat_app._access_ok())

    def test_matching_header_is_accepted(self):
        chat_app.ACCESS_CODE = "secret"
        with chat_app.app.test_request_context(headers={"X-Access-Code": "secret"}):
            self.assertTrue(chat_app._access_ok())

    def test_wrong_header_is_rejected(self):
        chat_app.ACCESS_CODE = "secret"
        with chat_app.app.test_request_context(headers={"X-Access-Code": "wrong"}):
            self.assertFalse(chat_app._access_ok())


class VerifyGoogleTokenTests(unittest.TestCase):
    def setUp(self):
        chat_app.GOOGLE_CLIENT_ID = "test-client-id"

    def test_no_client_id_configured_rejects(self):
        chat_app.GOOGLE_CLIENT_ID = ""
        self.assertIsNone(chat_app._verify_google_token("будь-який-токен"))

    def test_empty_token_rejects(self):
        self.assertIsNone(chat_app._verify_google_token(""))

    def test_valid_verified_email_is_accepted(self):
        payload = {
            "sub": "12345",
            "email": "user@gmail.com",
            "email_verified": True,
            "name": "Тест Тестовий",
            "picture": "https://example.com/pic.jpg",
        }
        with patch.object(chat_app.google_id_token, "verify_oauth2_token", return_value=payload):
            user = chat_app._verify_google_token("токен")
        self.assertEqual(user["email"], "user@gmail.com")
        self.assertEqual(user["sub"], "12345")

    def test_unverified_email_is_rejected(self):
        payload = {"sub": "1", "email": "user@gmail.com", "email_verified": False}
        with patch.object(chat_app.google_id_token, "verify_oauth2_token", return_value=payload):
            self.assertIsNone(chat_app._verify_google_token("токен"))

    def test_invalid_signature_is_rejected(self):
        with patch.object(chat_app.google_id_token, "verify_oauth2_token", side_effect=ValueError("bad token")):
            self.assertIsNone(chat_app._verify_google_token("токен"))


class ResolvePlaceTests(unittest.TestCase):
    """
    _resolve_place: спершу звичайний пошук (geocoding.py), і лише якщо
    він нічого не знайшов — просить AI назвати офіційну назву. AI сам
    (_ai_official_place_name) тут не викликає мережу — мокається окремо.
    """

    def test_direct_match_skips_ai_entirely(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", return_value=["9000"]) as geocode, \
             patch.object(chat_app, "_ai_official_place_name") as ai_call:
            codes, canonical = chat_app._resolve_place("Gent")
        self.assertEqual(codes, ["9000"])
        self.assertEqual(canonical, "Gent")
        ai_call.assert_not_called()
        geocode.assert_called_once()

    def test_known_ukrainian_alias_is_translated_even_without_ai(self):
        # "Гент" знаходиться одразу через geocoding.UKRAINIAN_ALIASES —
        # canonical мав би бути "Gent" (латиницею), а не сирий кириличний
        # текст, інакше localities-фільтр (порівняння з listing.locality,
        # завжди латиницею) ніколи б не збігався.
        with patch.object(chat_app.geocoding, "postal_codes_for_name", return_value=["9000"]), \
             patch.object(chat_app, "_ai_official_place_name") as ai_call:
            codes, canonical = chat_app._resolve_place("Гент")
        self.assertEqual(codes, ["9000"])
        self.assertEqual(canonical, "Gent")
        ai_call.assert_not_called()

    def test_ai_fallback_resolves_unknown_ukrainian_spelling(self):
        def fake_geocode(name):
            return ["9200"] if name == "Dendermonde" else []

        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=fake_geocode), \
             patch.object(chat_app, "_ai_official_place_name", return_value="Dendermonde"):
            codes, canonical = chat_app._resolve_place("Дендермонде")
        self.assertEqual(codes, ["9200"])
        self.assertEqual(canonical, "Dendermonde")

    def test_ai_fallback_also_failing_returns_empty(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", return_value=[]), \
             patch.object(chat_app, "_ai_official_place_name", return_value=None):
            codes, canonical = chat_app._resolve_place("Атлантида")
        self.assertEqual(codes, [])
        self.assertEqual(canonical, "Атлантида")

    def test_ai_disabled_when_no_api_key(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", return_value=[]), \
             patch.object(chat_app, "OPENROUTER_API_KEY", ""):
            self.assertIsNone(chat_app._ai_official_place_name("Дендермонде"))


class ValidateSubscriptionBodyTests(unittest.TestCase):
    def _geocode_ok(self, *args, **kwargs):
        return ["9000"]

    def test_missing_place_is_rejected(self):
        profile, error = chat_app._validate_subscription_body({"notify_email": "a@b.com", "interval_hours": 3})
        self.assertIsNone(profile)
        self.assertIn("місто", error.lower())

    def test_unknown_place_is_rejected(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", return_value=[]):
            profile, error = chat_app._validate_subscription_body(
                {"place": "Атлантида", "notify_email": "a@b.com", "interval_hours": 3}
            )
        self.assertIsNone(profile)
        self.assertIn("Атлантида", error)

    def test_bad_email_is_rejected(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body(
                {"place": "Gent", "notify_email": "not-an-email", "interval_hours": 3}
            )
        self.assertIsNone(profile)
        self.assertIn("пошту", error.lower())

    def test_interval_out_of_range_is_rejected(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body(
                {"place": "Gent", "notify_email": "a@b.com", "interval_hours": 9999}
            )
        self.assertIsNone(profile)
        self.assertIn("Інтервал", error)

    def test_valid_body_builds_profile(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent", "notify_email": "a@b.com", "interval_hours": 6,
                "transaction": "sale", "property_types": ["apartment"], "price_max": 800,
            })
        self.assertIsNone(error)
        self.assertEqual(profile["place"], "Gent")
        self.assertEqual(profile["interval_hours"], 6)
        self.assertEqual(profile["notify_email"], "a@b.com")
        self.assertEqual(profile["search"]["transaction"], "sale")
        self.assertEqual(profile["search"]["property_types"], ["apartment"])
        self.assertEqual(profile["search"]["postal_codes"], ["9000"])
        self.assertEqual(profile["search"]["price_max"], 800.0)
        self.assertIsInstance(profile["search"]["price_max"], float)

    def test_string_numbers_from_form_are_coerced(self):
        # HTML <input> завжди дає рядки — форма надсилає "800", не 800.
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent", "notify_email": "a@b.com", "interval_hours": "6",
                "price_min": "600", "bedrooms_min": "2", "living_area_min": "35",
            })
        self.assertIsNone(error)
        self.assertEqual(profile["interval_hours"], 6)
        self.assertEqual(profile["search"]["price_min"], 600.0)
        self.assertEqual(profile["search"]["bedrooms_min"], 2)
        self.assertEqual(profile["search"]["living_area_min"], 35.0)

    def test_empty_optional_numbers_become_none(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent", "notify_email": "a@b.com", "interval_hours": 6,
                "price_min": "", "bedrooms_max": None,
            })
        self.assertIsNone(error)
        self.assertIsNone(profile["search"]["price_min"])
        self.assertIsNone(profile["search"]["bedrooms_max"])

    def test_invalid_property_types_falls_back_to_both(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent", "notify_email": "a@b.com", "interval_hours": 6,
                "property_types": ["boat"],
            })
        self.assertIsNone(error)
        self.assertEqual(profile["search"]["property_types"], ["house", "apartment"])

    def test_multiple_cities_separated_by_comma(self):
        codes_by_name = {"Gent": ["9000"], "Kortrijk": ["8500", "8501"]}

        def fake_geocode(name):
            return codes_by_name.get(name, [])

        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=fake_geocode):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent, Kortrijk", "notify_email": "a@b.com", "interval_hours": 6,
            })
        self.assertIsNone(error)
        self.assertEqual(profile["place"], "Gent, Kortrijk")
        self.assertEqual(profile["search"]["localities"], ["Gent", "Kortrijk"])
        self.assertEqual(profile["search"]["postal_codes"], ["9000", "8500", "8501"])

    def test_ukrainian_city_names_resolved_via_ai_and_stored_canonically(self):
        # "Дендермонде"/"Локерен" не в geocoding.py -> перший пошук
        # порожній, AI називає офіційну назву, другий пошук уже вдалий.
        official_by_ukrainian = {"Дендермонде": "Dendermonde", "Локерен": "Lokeren"}
        codes_by_name = {"Dendermonde": ["9200"], "Lokeren": ["9160"]}

        def fake_geocode(name):
            return codes_by_name.get(name, [])

        def fake_ai(name):
            return official_by_ukrainian.get(name)

        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=fake_geocode), \
             patch.object(chat_app, "_ai_official_place_name", side_effect=fake_ai):
            profile, error = chat_app._validate_subscription_body({
                "place": "Дендермонде, Локерен", "notify_email": "a@b.com", "interval_hours": 6,
            })
        self.assertIsNone(error)
        # place (сирий текст із форми) лишається як людина написала —
        # лише пошук/фільтр усередині мають бути латиницею.
        self.assertEqual(profile["place"], "Дендермонде, Локерен")
        self.assertEqual(profile["search"]["localities"], ["Dendermonde", "Lokeren"])
        self.assertEqual(profile["search"]["postal_codes"], ["9200", "9160"])

    def test_bedrooms_max_below_min_is_rejected(self):
        # Саме цей стан ("від 1 до 0") мовчки перетворював профіль на
        # такий, що ніколи нічого не знайде — тепер відхиляється одразу.
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent", "notify_email": "a@b.com", "interval_hours": 6,
                "bedrooms_min": 1, "bedrooms_max": 0,
            })
        self.assertIsNone(profile)
        self.assertIn("Спалень", error)

    def test_price_max_below_min_is_rejected(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent", "notify_email": "a@b.com", "interval_hours": 6,
                "price_min": 800, "price_max": 600,
            })
        self.assertIsNone(profile)
        self.assertIn("Ціна", error)

    def test_equal_min_and_max_bedrooms_is_allowed(self):
        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=self._geocode_ok):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent", "notify_email": "a@b.com", "interval_hours": 6,
                "bedrooms_min": 1, "bedrooms_max": 1,
            })
        self.assertIsNone(error)
        self.assertEqual(profile["search"]["bedrooms_min"], 1)
        self.assertEqual(profile["search"]["bedrooms_max"], 1)

    def test_one_unknown_city_among_several_is_rejected_by_name(self):
        codes_by_name = {"Gent": ["9000"]}

        def fake_geocode(name):
            return codes_by_name.get(name, [])

        with patch.object(chat_app.geocoding, "postal_codes_for_name", side_effect=fake_geocode):
            profile, error = chat_app._validate_subscription_body({
                "place": "Gent, Атлантида", "notify_email": "a@b.com", "interval_hours": 6,
            })
        self.assertIsNone(profile)
        self.assertIn("Атлантида", error)


if __name__ == "__main__":
    unittest.main()
