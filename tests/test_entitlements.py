"""Тести для aggregator/entitlements.py — логіка підписок, без мережі й файлів."""

import unittest
from datetime import datetime, timedelta, timezone

from aggregator import entitlements


NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def _entry(**over):
    base = {
        "status": "active",
        "plan": "pro",
        "granted_by": "owner@gmail.com",
        "granted_utc": "2026-09-01T00:00:00+00:00",
        "expires_utc": None,
        "note": "",
    }
    base.update(over)
    return base


class NormalizeEmailTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(entitlements.normalize_email("  Foo@Bar.COM "), "foo@bar.com")

    def test_none_becomes_empty(self):
        self.assertEqual(entitlements.normalize_email(None), "")


class IsActiveTests(unittest.TestCase):
    def test_active_without_expiry(self):
        self.assertTrue(entitlements.is_active(_entry(), NOW))

    def test_active_with_future_expiry(self):
        future = (NOW + timedelta(days=1)).isoformat()
        self.assertTrue(entitlements.is_active(_entry(expires_utc=future), NOW))

    def test_expired_is_not_active(self):
        past = (NOW - timedelta(days=1)).isoformat()
        self.assertFalse(entitlements.is_active(_entry(expires_utc=past), NOW))

    def test_revoked_is_not_active(self):
        self.assertFalse(entitlements.is_active(_entry(status="revoked"), NOW))

    def test_empty_entry_is_not_active(self):
        self.assertFalse(entitlements.is_active(None, NOW))
        self.assertFalse(entitlements.is_active({}, NOW))

    def test_unparseable_expiry_is_treated_as_no_expiry(self):
        self.assertTrue(entitlements.is_active(_entry(expires_utc="колись"), NOW))


class EntitlementForTests(unittest.TestCase):
    def test_admin_is_always_active_even_without_entry(self):
        result = entitlements.entitlement_for({}, "Owner@Gmail.com", ["owner@gmail.com"], NOW)
        self.assertTrue(result["active"])
        self.assertTrue(result["is_admin"])
        self.assertEqual(result["plan"], "admin")

    def test_active_subscriber(self):
        store = {"a@b.com": _entry()}
        result = entitlements.entitlement_for(store, "a@b.com", ["owner@gmail.com"], NOW)
        self.assertTrue(result["active"])
        self.assertFalse(result["is_admin"])
        self.assertEqual(result["status"], "active")

    def test_unknown_email_is_inactive(self):
        result = entitlements.entitlement_for({}, "stranger@x.com", ["owner@gmail.com"], NOW)
        self.assertFalse(result["active"])
        self.assertEqual(result["status"], "none")

    def test_expired_subscriber_is_inactive_but_status_kept(self):
        past = (NOW - timedelta(days=1)).isoformat()
        store = {"a@b.com": _entry(expires_utc=past)}
        result = entitlements.entitlement_for(store, "a@b.com", [], NOW)
        self.assertFalse(result["active"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["expires_utc"], past)


class UpsertTests(unittest.TestCase):
    def test_adds_new_entry_without_touching_original(self):
        store = {}
        updated = entitlements.upsert(store, "New@X.com", granted_by="owner@gmail.com", now=NOW)
        self.assertEqual(store, {})  # оригінал не змінено
        self.assertIn("new@x.com", updated)
        self.assertEqual(updated["new@x.com"]["status"], "active")
        self.assertEqual(updated["new@x.com"]["granted_by"], "owner@gmail.com")

    def test_keeps_granted_utc_on_update(self):
        store = entitlements.upsert({}, "a@b.com", now=NOW)
        later = NOW + timedelta(days=5)
        updated = entitlements.upsert(store, "a@b.com", status="revoked", now=later)
        self.assertEqual(updated["a@b.com"]["granted_utc"], store["a@b.com"]["granted_utc"])
        self.assertEqual(updated["a@b.com"]["status"], "revoked")

    def test_rejects_bad_status(self):
        with self.assertRaises(ValueError):
            entitlements.upsert({}, "a@b.com", status="maybe")

    def test_rejects_bad_expiry(self):
        with self.assertRaises(ValueError):
            entitlements.upsert({}, "a@b.com", expires_utc="next tuesday")

    def test_rejects_empty_email(self):
        with self.assertRaises(ValueError):
            entitlements.upsert({}, "   ")


class RemoveTests(unittest.TestCase):
    def test_removes_entry(self):
        store = {"a@b.com": _entry()}
        updated = entitlements.remove(store, "A@B.com")
        self.assertEqual(updated, {})
        self.assertIn("a@b.com", store)  # оригінал не змінено

    def test_missing_email_is_noop(self):
        self.assertEqual(entitlements.remove({}, "nobody@x.com"), {})


if __name__ == "__main__":
    unittest.main()
