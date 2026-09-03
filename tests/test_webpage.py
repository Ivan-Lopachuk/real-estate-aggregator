"""
Тести для aggregator/webpage.py.

Перевіряємо лише _build_listings — чистий Python, без файлів і бази.
Він відповідає за те, щоб дублікат (оголошення з іншого сайту, яке
runner.py вже позначив як duplicate_of) не ставав окремою карткою на
дошці, а лише посиланням "also_on" при оригіналі.
"""

import unittest

from aggregator.webpage import _build_listings


def row(uid, site="immoweb", duplicate_of=None, **extra):
    base = {
        "uid": uid, "site": site, "url": f"https://example.com/{uid}",
        "title": uid, "price": 700, "currency": "EUR", "transaction_kind": "rent",
        "property_type": "apartment", "bedrooms": 1, "living_area": 40,
        "locality": "Gent", "postal_code": "9000", "street": "Kerkstraat",
        "house_number": "1", "photo_url": None, "fiber_available": None,
        "first_seen_utc": "2026-01-01T00:00:00+00:00", "duplicate_of": duplicate_of,
    }
    base.update(extra)
    return base


class BuildListingsTests(unittest.TestCase):
    def test_non_duplicate_rows_all_become_cards(self):
        rows = [row("a"), row("b", site="zimmo")]
        listings = _build_listings(rows)
        self.assertEqual({l["uid"] for l in listings}, {"a", "b"})
        self.assertNotIn("also_on", listings[0])

    def test_duplicate_is_attached_to_original_instead_of_own_card(self):
        rows = [row("a"), row("b", site="zimmo", duplicate_of="a")]
        listings = _build_listings(rows)
        self.assertEqual([l["uid"] for l in listings], ["a"])
        self.assertEqual(listings[0]["also_on"], [{"site": "zimmo", "url": "https://example.com/b"}])

    def test_multiple_duplicates_of_the_same_original_all_attach(self):
        rows = [
            row("a"),
            row("b", site="zimmo", duplicate_of="a"),
            row("c", site="zimmo", duplicate_of="a"),
        ]
        listings = _build_listings(rows)
        self.assertEqual([l["uid"] for l in listings], ["a"])
        self.assertEqual(len(listings[0]["also_on"]), 2)

    def test_duplicate_without_its_original_in_range_is_dropped_quietly(self):
        rows = [row("b", site="zimmo", duplicate_of="missing")]
        self.assertEqual(_build_listings(rows), [])


if __name__ == "__main__":
    unittest.main()
