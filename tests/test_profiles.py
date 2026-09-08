"""Тести для aggregator/profiles.py — читання profiles/*.json і is_due()."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aggregator.profiles import load_profiles, mark_checked


def _write_profile(directory: Path, name: str, **fields) -> Path:
    base = {
        "google_sub": "123",
        "notify_email": "a@b.com",
        "interval_hours": 3,
        "search": {"transaction": "rent", "postal_codes": ["9000"]},
        "last_sent_utc": None,
    }
    base.update(fields)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


class LoadProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_directory_returns_empty(self):
        self.assertEqual(load_profiles(self.dir / "nope"), [])

    def test_reads_valid_profile(self):
        _write_profile(self.dir, "user1", notify_email="me@example.com", interval_hours=6)
        profiles = load_profiles(self.dir)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].notify_email, "me@example.com")
        self.assertEqual(profiles[0].interval_hours, 6)
        self.assertEqual(profiles[0].id, "user1")
        self.assertEqual(profiles[0].search.postal_codes, ["9000"])

    def test_skips_broken_json(self):
        (self.dir / "broken.json").write_text("{not valid json", encoding="utf-8")
        _write_profile(self.dir, "good")
        profiles = load_profiles(self.dir)
        self.assertEqual([p.id for p in profiles], ["good"])

    def test_skips_profile_missing_notify_email(self):
        path = self.dir / "incomplete.json"
        path.write_text(json.dumps({"interval_hours": 3, "search": {}}), encoding="utf-8")
        self.assertEqual(load_profiles(self.dir), [])

    def test_ignores_non_json_files(self):
        (self.dir / "readme.txt").write_text("hello", encoding="utf-8")
        self.assertEqual(load_profiles(self.dir), [])


class IsDueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_never_checked_is_due(self):
        _write_profile(self.dir, "p", last_sent_utc=None)
        profile = load_profiles(self.dir)[0]
        self.assertTrue(profile.is_due())

    def test_recently_checked_is_not_due(self):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        _write_profile(self.dir, "p", interval_hours=3, last_sent_utc=recent)
        profile = load_profiles(self.dir)[0]
        self.assertFalse(profile.is_due())

    def test_overdue_is_due(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(timespec="seconds")
        _write_profile(self.dir, "p", interval_hours=3, last_sent_utc=old)
        profile = load_profiles(self.dir)[0]
        self.assertTrue(profile.is_due())


class MarkCheckedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_updates_last_sent_utc_in_file(self):
        _write_profile(self.dir, "p", last_sent_utc=None)
        profile = load_profiles(self.dir)[0]
        self.assertTrue(profile.is_due())

        mark_checked(profile)

        reloaded = load_profiles(self.dir)[0]
        self.assertFalse(reloaded.is_due())
        self.assertIsNotNone(reloaded.last_sent_utc)

    def test_preserves_other_fields(self):
        _write_profile(self.dir, "p", notify_email="keep@me.com")
        profile = load_profiles(self.dir)[0]
        mark_checked(profile)
        reloaded = load_profiles(self.dir)[0]
        self.assertEqual(reloaded.notify_email, "keep@me.com")


if __name__ == "__main__":
    unittest.main()
