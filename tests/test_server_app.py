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
        # Дати рахуємо відносно «зараз», щоб тест не старів із часом.
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        recent = Listing(site="immoweb", site_listing_id="1", url="u1", title="t1",
                          listed_at=(now - timedelta(hours=6)).isoformat())
        old = Listing(site="zimmo", site_listing_id="2", url="u2", title="t2",
                       listed_at=(now - timedelta(days=30)).isoformat())
        unknown = Listing(site="immoweb", site_listing_id="3", url="u3", title="t3", listed_at=None)

        kept = chat_app._apply_recency([recent, old, unknown], 2)
        self.assertEqual({l.uid for l in kept}, {"immoweb:1", "immoweb:3"})

    def test_no_days_back_keeps_everything(self):
        listings = [Listing(site="immoweb", site_listing_id="1", url="u1", title="t1")]
        self.assertEqual(chat_app._apply_recency(listings, None), listings)


class GateTests(unittest.TestCase):
    """
    _gate() / _subscribed_user() — головний вартовий закритих ендпоїнтів:
    потрібен і вхід через Google, і активна підписка (або статус адміна).
    Раніше тут був окремий "код доступу" (X-Access-Code) — його прибрано.
    """

    def setUp(self):
        chat_app.ADMIN_EMAILS = "owner@gmail.com"

    def test_no_login_returns_401(self):
        with patch.object(chat_app, "_authenticated_user", return_value=None):
            with chat_app.app.test_request_context():
                _user, denied = chat_app._gate()
        self.assertEqual(denied[1], 401)

    def test_logged_in_without_subscription_returns_402(self):
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "x@y.com", "sub": "1"}), \
             patch.object(chat_app, "_read_subscription_store", return_value={}):
            with chat_app.app.test_request_context():
                user, denied = chat_app._gate()
        self.assertIsNone(user)
        self.assertEqual(denied[1], 402)

    def test_active_subscriber_passes(self):
        store = {"x@y.com": {"status": "active", "plan": "pro", "expires_utc": None}}
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "x@y.com", "sub": "1"}), \
             patch.object(chat_app, "_read_subscription_store", return_value=store):
            with chat_app.app.test_request_context():
                user, denied = chat_app._gate()
        self.assertIsNone(denied)
        self.assertEqual(user["email"], "x@y.com")

    def test_admin_passes_without_any_subscription_file(self):
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "owner@gmail.com", "sub": "9"}), \
             patch.object(chat_app, "_read_subscription_store", return_value={}):
            with chat_app.app.test_request_context():
                user, denied = chat_app._gate()
        self.assertIsNone(denied)
        self.assertEqual(user["email"], "owner@gmail.com")


class MeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = chat_app.app.test_client()
        chat_app.ADMIN_EMAILS = "owner@gmail.com"

    def test_without_login_is_401(self):
        with patch.object(chat_app, "_authenticated_user", return_value=None):
            resp = self.client.get("/api/me")
        self.assertEqual(resp.status_code, 401)

    def test_reports_admin_entitlement(self):
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "owner@gmail.com", "sub": "9"}), \
             patch.object(chat_app, "_read_subscription_store", return_value={}):
            resp = self.client.get("/api/me", headers={"Authorization": "Bearer x"})
        data = resp.get_json()
        self.assertTrue(data["entitlement"]["active"])
        self.assertTrue(data["entitlement"]["is_admin"])

    def test_reports_inactive_for_stranger(self):
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "s@x.com", "sub": "2"}), \
             patch.object(chat_app, "_read_subscription_store", return_value={}):
            resp = self.client.get("/api/me", headers={"Authorization": "Bearer x"})
        self.assertFalse(resp.get_json()["entitlement"]["active"])


class AdminSubscriptionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = chat_app.app.test_client()
        chat_app.ADMIN_EMAILS = "owner@gmail.com"
        chat_app.GH_WRITE_TOKEN = "tok"
        chat_app.GH_REPO = "me/repo"

    def test_non_admin_is_403(self):
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "s@x.com", "sub": "2"}), \
             patch.object(chat_app, "_read_subscription_store", return_value={}):
            resp = self.client.get("/api/admin/subscriptions", headers={"Authorization": "Bearer x"})
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_grant(self):
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "owner@gmail.com", "sub": "9"}), \
             patch.object(chat_app, "_read_subscription_store", return_value={}), \
             patch.object(chat_app, "read_json", return_value=({}, "sha")), \
             patch.object(chat_app, "write_json") as mock_write:
            resp = self.client.post(
                "/api/admin/subscriptions", headers={"Authorization": "Bearer x"},
                json={"email": "Friend@Example.com", "expires_utc": "2026-12-31T00:00:00+00:00"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("friend@example.com", resp.get_json()["subscriptions"])
        mock_write.assert_called_once()

    def test_admin_grant_rejects_bad_date(self):
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "owner@gmail.com", "sub": "9"}), \
             patch.object(chat_app, "_read_subscription_store", return_value={}), \
             patch.object(chat_app, "read_json", return_value=({}, "sha")), \
             patch.object(chat_app, "write_json"):
            resp = self.client.post(
                "/api/admin/subscriptions", headers={"Authorization": "Bearer x"},
                json={"email": "friend@example.com", "expires_utc": "колись"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_admin_can_revoke(self):
        store = {"friend@example.com": {"status": "active"}}
        with patch.object(chat_app, "_authenticated_user", return_value={"email": "owner@gmail.com", "sub": "9"}), \
             patch.object(chat_app, "_read_subscription_store", return_value=store), \
             patch.object(chat_app, "read_json", return_value=(store, "sha")), \
             patch.object(chat_app, "write_json") as mock_write:
            resp = self.client.delete(
                "/api/admin/subscriptions", headers={"Authorization": "Bearer x"},
                json={"email": "friend@example.com"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("friend@example.com", resp.get_json()["subscriptions"])
        mock_write.assert_called_once()


class FeedEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = chat_app.app.test_client()
        chat_app.ADMIN_EMAILS = "owner@gmail.com"
        chat_app.GH_WRITE_TOKEN = "tok"
        chat_app.GH_REPO = "me/repo"
        self._gate_patch = patch.object(
            chat_app, "_gate", return_value=({"sub": "42", "email": "owner@gmail.com"}, None)
        )
        self._gate_patch.start()

    def tearDown(self):
        self._gate_patch.stop()

    def test_get_feed_returns_items_and_unread(self):
        data = {"items": [{"uid": "immoweb:1", "read": False}, {"uid": "immoweb:2", "read": True}]}
        with patch.object(chat_app, "read_json", return_value=(data, "sha")):
            resp = self.client.get("/api/feed", headers={"Authorization": "Bearer x"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["unread"], 1)

    def test_mark_all_read(self):
        data = {"items": [{"uid": "immoweb:1", "read": False}]}
        with patch.object(chat_app, "read_json", return_value=(data, "sha")), \
             patch.object(chat_app, "write_json") as mock_write:
            resp = self.client.post(
                "/api/feed/read", headers={"Authorization": "Bearer x"}, json={"all": True}
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["unread"], 0)
        self.assertEqual(mock_write.call_args[0][2], "feed/42.json")

    def test_chat_without_subscription_is_blocked(self):
        self._gate_patch.stop()
        with patch.object(chat_app, "_gate", return_value=(None, ("Потрібна підписка", 402))):
            resp = self.client.post("/api/chat", json={"message": "привіт"})
        self.assertEqual(resp.status_code, 402)
        self._gate_patch.start()


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


class SeenEndpointTests(unittest.TestCase):
    """
    /api/seen — синхронізація позначок "переглянуто" між пристроями для
    залогінених через Google акаунтів. Авторизація тут та сама, що й у
    розсилки (Bearer <session_token>, див. _authenticated_user) —
    мокаємо саме її, щоб не чіпати справжню перевірку підпису Google.
    """

    def setUp(self):
        self.client = chat_app.app.test_client()
        chat_app.GH_WRITE_TOKEN = "tok"
        chat_app.GH_REPO = "me/repo"
        self._user_patch = patch.object(
            chat_app, "_authenticated_user", return_value={"sub": "42", "email": "a@b.com"}
        )
        self._user_patch.start()
        # Ці ендпоїнти тепер за підпискою (_gate) — вважаємо користувача активним.
        self._ent_patch = patch.object(
            chat_app, "_entitlement_for", return_value={"active": True, "is_admin": False}
        )
        self._ent_patch.start()

    def tearDown(self):
        self._ent_patch.stop()
        self._user_patch.stop()

    def test_get_returns_empty_map_when_no_file_yet(self):
        with patch.object(chat_app, "read_json", return_value=(None, None)):
            resp = self.client.get("/api/seen", headers={"Authorization": "Bearer x"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"seen": {}})

    def test_get_returns_existing_map(self):
        with patch.object(chat_app, "read_json", return_value=({"immoweb:1": "2026-01-01T00:00:00"}, "sha1")):
            resp = self.client.get("/api/seen", headers={"Authorization": "Bearer x"})
        self.assertEqual(resp.get_json(), {"seen": {"immoweb:1": "2026-01-01T00:00:00"}})

    def test_get_without_auth_is_rejected(self):
        self._user_patch.stop()
        with patch.object(chat_app, "_authenticated_user", return_value=None):
            resp = self.client.get("/api/seen")
        self.assertEqual(resp.status_code, 401)
        self._user_patch.start()

    def test_post_saves_map_and_returns_it(self):
        with patch.object(chat_app, "read_json", return_value=(None, None)), \
             patch.object(chat_app, "write_json") as mock_write:
            resp = self.client.post(
                "/api/seen", headers={"Authorization": "Bearer x"},
                json={"seen": {"immoweb:1": "2026-01-01T00:00:00"}},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"seen": {"immoweb:1": "2026-01-01T00:00:00"}})
        mock_write.assert_called_once()
        self.assertEqual(mock_write.call_args[0][2], "seen/42.json")

    def test_post_rejects_non_dict_body(self):
        with patch.object(chat_app, "read_json", return_value=(None, None)):
            resp = self.client.post(
                "/api/seen", headers={"Authorization": "Bearer x"}, json={"seen": ["not", "a", "map"]}
            )
        self.assertEqual(resp.status_code, 400)

    def test_post_rejects_non_string_values(self):
        with patch.object(chat_app, "read_json", return_value=(None, None)):
            resp = self.client.post(
                "/api/seen", headers={"Authorization": "Bearer x"}, json={"seen": {"immoweb:1": 12345}}
            )
        self.assertEqual(resp.status_code, 400)


class FavoritesEndpointTests(unittest.TestCase):
    """/api/favorites — та сама механіка, що й /api/seen, окремий файл."""

    def setUp(self):
        self.client = chat_app.app.test_client()
        chat_app.GH_WRITE_TOKEN = "tok"
        chat_app.GH_REPO = "me/repo"
        self._user_patch = patch.object(
            chat_app, "_authenticated_user", return_value={"sub": "42", "email": "a@b.com"}
        )
        self._user_patch.start()
        self._ent_patch = patch.object(
            chat_app, "_entitlement_for", return_value={"active": True, "is_admin": False}
        )
        self._ent_patch.start()

    def tearDown(self):
        self._ent_patch.stop()
        self._user_patch.stop()

    def test_get_returns_empty_map_when_no_file_yet(self):
        with patch.object(chat_app, "read_json", return_value=(None, None)):
            resp = self.client.get("/api/favorites", headers={"Authorization": "Bearer x"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"favorites": {}})

    def test_post_saves_map_to_favorites_path_and_returns_it(self):
        with patch.object(chat_app, "read_json", return_value=(None, None)), \
             patch.object(chat_app, "write_json") as mock_write:
            resp = self.client.post(
                "/api/favorites", headers={"Authorization": "Bearer x"},
                json={"favorites": {"immoweb:1": "2026-01-01T00:00:00"}},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"favorites": {"immoweb:1": "2026-01-01T00:00:00"}})
        self.assertEqual(mock_write.call_args[0][2], "favorites/42.json")

    def test_post_rejects_bad_format(self):
        with patch.object(chat_app, "read_json", return_value=(None, None)):
            resp = self.client.post(
                "/api/favorites", headers={"Authorization": "Bearer x"},
                json={"favorites": {"immoweb:1": 123}},
            )
        self.assertEqual(resp.status_code, 400)

    def test_get_without_auth_is_rejected(self):
        self._user_patch.stop()
        with patch.object(chat_app, "_authenticated_user", return_value=None):
            resp = self.client.get("/api/favorites")
        self.assertEqual(resp.status_code, 401)
        self._user_patch.start()


class SessionTokenTests(unittest.TestCase):
    """
    Токен, який сервер видає ПІСЛЯ входу через Google (30 днів) — щоб
    людина не мусила заходити знову при кожному оновленні дошки. Не
    плутати з самим токеном Google, який живе лише ~годину.
    """

    def _user(self):
        return {"sub": "1", "email": "a@b.com", "name": "A", "picture": "http://pic"}

    def test_round_trip(self):
        token = chat_app._make_session_token(self._user())
        payload = chat_app._verify_session_token(token)
        self.assertEqual(payload["sub"], "1")
        self.assertEqual(payload["email"], "a@b.com")

    def test_tampered_token_is_rejected(self):
        token = chat_app._make_session_token(self._user())
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        self.assertIsNone(chat_app._verify_session_token(tampered))

    def test_expired_token_is_rejected(self):
        with patch.object(chat_app, "SESSION_TTL_SECONDS", -10):
            token = chat_app._make_session_token(self._user())
        self.assertIsNone(chat_app._verify_session_token(token))

    def test_garbage_token_is_rejected(self):
        self.assertIsNone(chat_app._verify_session_token("not-a-real-token"))


if __name__ == "__main__":
    unittest.main()
