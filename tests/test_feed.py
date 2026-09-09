"""Тести для aggregator/feed.py — стрічка сповіщень у кабінеті."""

import tempfile
import unittest
from pathlib import Path

from aggregator import feed
from aggregator.models import Listing


def _listing(n: int) -> Listing:
    return Listing(
        site="immoweb", site_listing_id=str(n), url=f"https://example.com/{n}",
        title=f"Квартира {n}", price=700 + n, locality="Gent", postal_code="9000",
    )


SENT = "2026-09-09T10:00:00+00:00"


class ListingToItemTests(unittest.TestCase):
    def test_maps_fields_and_is_unread(self):
        item = feed.listing_to_item(_listing(1), SENT)
        self.assertEqual(item["uid"], "immoweb:1")
        self.assertEqual(item["title"], "Квартира 1")
        self.assertEqual(item["sent_utc"], SENT)
        self.assertFalse(item["read"])


class AppendItemsTests(unittest.TestCase):
    def test_new_items_go_on_top(self):
        first = feed.append_items({"items": []}, [_listing(1)], SENT)
        second = feed.append_items(first, [_listing(2)], "2026-09-10T10:00:00+00:00")
        self.assertEqual([i["uid"] for i in second["items"]], ["immoweb:2", "immoweb:1"])

    def test_duplicate_uid_is_not_added_again(self):
        first = feed.append_items({"items": []}, [_listing(1)], SENT)
        again = feed.append_items(first, [_listing(1), _listing(2)], "2026-09-11T00:00:00+00:00")
        self.assertEqual([i["uid"] for i in again["items"]], ["immoweb:2", "immoweb:1"])

    def test_cap_trims_oldest(self):
        result = {"items": []}
        for n in range(5):
            result = feed.append_items(result, [_listing(n)], SENT, cap=3)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual([i["uid"] for i in result["items"]],
                         ["immoweb:4", "immoweb:3", "immoweb:2"])

    def test_does_not_mutate_input(self):
        original = {"items": []}
        feed.append_items(original, [_listing(1)], SENT)
        self.assertEqual(original, {"items": []})


class MarkReadTests(unittest.TestCase):
    def test_mark_all(self):
        f = feed.append_items({"items": []}, [_listing(1), _listing(2)], SENT)
        marked = feed.mark_read(f)
        self.assertTrue(all(i["read"] for i in marked["items"]))

    def test_mark_specific_uids(self):
        f = feed.append_items({"items": []}, [_listing(1), _listing(2)], SENT)
        marked = feed.mark_read(f, ["immoweb:1"])
        by_uid = {i["uid"]: i["read"] for i in marked["items"]}
        self.assertTrue(by_uid["immoweb:1"])
        self.assertFalse(by_uid["immoweb:2"])


class UnreadCountTests(unittest.TestCase):
    def test_counts_unread(self):
        f = feed.append_items({"items": []}, [_listing(1), _listing(2), _listing(3)], SENT)
        self.assertEqual(feed.unread_count(f), 3)
        f = feed.mark_read(f, ["immoweb:2"])
        self.assertEqual(feed.unread_count(f), 2)

    def test_empty_feed(self):
        self.assertEqual(feed.unread_count(None), 0)
        self.assertEqual(feed.unread_count({"items": []}), 0)


class LoadSaveFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_empty_feed(self):
        self.assertEqual(feed.load_feed(self.dir, "123"), {"items": []})

    def test_round_trip(self):
        f = feed.append_items({"items": []}, [_listing(1)], SENT)
        feed.save_feed(self.dir, "123", f)
        self.assertEqual(feed.load_feed(self.dir, "123"), f)

    def test_broken_file_returns_empty_feed(self):
        (self.dir / "123.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(feed.load_feed(self.dir, "123"), {"items": []})


if __name__ == "__main__":
    unittest.main()
