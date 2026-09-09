"""Тести для aggregator/runner.py (лише формування посилання, без мережі)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aggregator.config import (
    Config, EmailSettings, FiberCheckSettings, HttpSettings, NotificationSettings,
    SearchCriteria, WebpageSettings,
)
from aggregator.database import Database
from aggregator.models import Listing
from aggregator.proximus import FiberAvailability
from aggregator import feed as feed_module
from aggregator.runner import _dashboard_link_for_batch, _dashboard_link_for_uids, run_profiles


class DashboardLinkForBatchTests(unittest.TestCase):
    def test_appends_since_param(self):
        url = _dashboard_link_for_batch("https://example.github.io/board/", "2026-09-03T12:00:00+00:00")
        self.assertEqual(url, "https://example.github.io/board/?since=2026-09-03T12%3A00%3A00%2B00%3A00")

    def test_empty_page_url_stays_empty(self):
        self.assertEqual(_dashboard_link_for_batch("", "2026-09-03T12:00:00+00:00"), "")

    def test_appends_with_ampersand_if_url_already_has_query(self):
        url = _dashboard_link_for_batch("https://example.com/?x=1", "2026-01-01T00:00:00+00:00")
        self.assertTrue(url.startswith("https://example.com/?x=1&since="))


class DashboardLinkForUidsTests(unittest.TestCase):
    def test_appends_ids_param(self):
        url = _dashboard_link_for_uids("https://example.github.io/board/", ["immoweb:1", "zimmo:2"])
        self.assertEqual(url, "https://example.github.io/board/?ids=immoweb%3A1%2Czimmo%3A2")

    def test_empty_page_url_stays_empty(self):
        self.assertEqual(_dashboard_link_for_uids("", ["immoweb:1"]), "")

    def test_empty_uids_stays_unchanged(self):
        self.assertEqual(_dashboard_link_for_uids("https://example.com/", []), "https://example.com/")


class _FakeScraper:
    """Підробний scraper — завжди повертає одне й те саме оголошення, без мережі."""

    def __init__(self, criteria, http):
        self.criteria = criteria

    def fetch(self):
        return [
            Listing(
                site="immoweb", site_listing_id="1", url="https://example.com/1", title="Квартира",
                transaction="rent", property_type="apartment", postal_code="9000", price=700,
            )
        ]


class _FakeScraperWithAddress:
    """Те саме, але з відомою адресою — щоб перевірити виклик Proximus."""

    def __init__(self, criteria, http):
        self.criteria = criteria

    def fetch(self):
        return [
            Listing(
                site="immoweb", site_listing_id="1", url="https://example.com/1", title="Квартира",
                transaction="rent", property_type="apartment", postal_code="9000", price=700,
                street="Kerkstraat", house_number="1", locality="Gent",
            )
        ]


def _make_config(
    database_path, webpage_url: str = "", output_dir: str = "", fiber_enabled: bool = False,
) -> Config:
    return Config(
        sites=["fake"],
        search=SearchCriteria(),
        http=HttpSettings(),
        notifications=NotificationSettings(
            method="email",
            email=EmailSettings(
                smtp_host="smtp.example.com", smtp_port=587, username="me@example.com",
                from_address="me@example.com", to_addresses=["owner@example.com"],
            ),
        ),
        database_path=database_path,
        poll_interval_minutes=60,
        webpage=WebpageSettings(
            enabled=bool(webpage_url), output_dir=output_dir or "docs", url=webpage_url
        ),
        fiber_check=FiberCheckSettings(enabled=fiber_enabled),
    )


def _write_profile(directory: Path, name: str = "user1", **overrides) -> None:
    data = {
        "google_sub": "123",
        "notify_email": "friend@example.com",
        "interval_hours": 1,
        "search": {"transaction": "rent", "postal_codes": ["9000"]},
        "last_sent_utc": None,
    }
    data.update(overrides)
    (directory / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


class RunProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db_path = self.dir / "listings.db"
        self.profiles_dir = self.dir / "profiles"
        self.profiles_dir.mkdir()
        self.feed_dir = self.dir / "feed"
        self.config = _make_config(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sends_email_to_profile_address_and_counts_it(self):
        _write_profile(self.profiles_dir)
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraper), \
             patch("aggregator.runner.EmailNotifier") as mock_notifier_cls:
            mock_notifier_cls.return_value.notify.return_value = None
            sent = run_profiles(self.config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)

        self.assertEqual(sent, 1)
        mock_notifier_cls.assert_called_once()
        called_settings = mock_notifier_cls.call_args[0][0]
        self.assertEqual(called_settings.to_addresses, ["friend@example.com"])

    def test_writes_notified_listings_into_the_cabinet_feed(self):
        _write_profile(self.profiles_dir, google_sub="abc123")
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraper), \
             patch("aggregator.runner.EmailNotifier") as mock_notifier_cls:
            mock_notifier_cls.return_value.notify.return_value = None
            run_profiles(
                self.config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir
            )

        stored = feed_module.load_feed(self.feed_dir, "abc123")
        self.assertEqual([i["uid"] for i in stored["items"]], ["immoweb:1"])
        self.assertEqual(feed_module.unread_count(stored), 1)

    def test_second_run_right_after_sends_nothing_new(self):
        _write_profile(self.profiles_dir)
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraper), \
             patch("aggregator.runner.EmailNotifier") as mock_notifier_cls:
            mock_notifier_cls.return_value.notify.return_value = None
            run_profiles(self.config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)
            second = run_profiles(self.config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)

        # Профіль щойно перевіряли (interval_hours=1) — вдруге ще не час.
        self.assertEqual(second, 0)
        mock_notifier_cls.assert_called_once()

    def test_no_profiles_directory_returns_zero(self):
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraper):
            sent = run_profiles(self.config, profiles_dir=self.dir / "does-not-exist")
        self.assertEqual(sent, 0)

    def test_no_smtp_configured_skips_silently(self):
        _write_profile(self.profiles_dir)
        config = _make_config(self.db_path)
        config.notifications.email = None
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraper):
            sent = run_profiles(config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)
        self.assertEqual(sent, 0)

    def test_email_gets_a_dashboard_link_when_webpage_enabled(self):
        _write_profile(self.profiles_dir)
        docs_dir = self.dir / "docs"
        config = _make_config(
            self.db_path, webpage_url="https://example.github.io/board/", output_dir=str(docs_dir)
        )
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraper), \
             patch("aggregator.runner.EmailNotifier") as mock_notifier_cls:
            mock_notifier_cls.return_value.notify.return_value = None
            run_profiles(config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)

        mock_notifier_cls.assert_called_once()
        page_url = mock_notifier_cls.call_args[0][1]
        # За id, а не за часом — бо оголошення могло вже бути в базі
        # від раніше (див. _dashboard_link_for_uids).
        self.assertTrue(page_url.startswith("https://example.github.io/board/?ids="))
        self.assertIn("immoweb%3A1", page_url)
        # А сама дошка (data.json) справді оновилась — інакше посилання вело б у порожнечу.
        self.assertTrue((docs_dir / "data.json").exists())

    def test_no_dashboard_link_when_webpage_disabled(self):
        _write_profile(self.profiles_dir)
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraper), \
             patch("aggregator.runner.EmailNotifier") as mock_notifier_cls:
            mock_notifier_cls.return_value.notify.return_value = None
            run_profiles(self.config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)

        page_url = mock_notifier_cls.call_args[0][1]
        self.assertEqual(page_url, "")

    def test_fiber_is_checked_for_profile_listings_when_enabled(self):
        _write_profile(self.profiles_dir)
        config = _make_config(self.db_path, fiber_enabled=True)
        fake_result = FiberAvailability(available=True, technology="FTTHBF")
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraperWithAddress), \
             patch("aggregator.runner.EmailNotifier") as mock_notifier_cls, \
             patch("aggregator.runner.proximus.check_fiber", return_value=fake_result) as mock_check:
            mock_notifier_cls.return_value.notify.return_value = None
            run_profiles(config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)

        mock_check.assert_called_once_with("Kerkstraat", "1", "9000", "Gent")
        with Database(self.db_path) as db:
            self.assertEqual(db.known_fiber_status("Kerkstraat", "1", "9000"), (True, "FTTHBF"))

    def test_fiber_not_checked_when_disabled(self):
        _write_profile(self.profiles_dir)
        config = _make_config(self.db_path, fiber_enabled=False)
        with patch("aggregator.runner.get_scraper", return_value=_FakeScraperWithAddress), \
             patch("aggregator.runner.EmailNotifier") as mock_notifier_cls, \
             patch("aggregator.runner.proximus.check_fiber") as mock_check:
            mock_notifier_cls.return_value.notify.return_value = None
            run_profiles(config, profiles_dir=self.profiles_dir, feed_dir=self.feed_dir)

        mock_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
