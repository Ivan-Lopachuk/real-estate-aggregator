"""Тести бази даних (дедуплікація). Запуск:  python -m unittest"""

import tempfile
import unittest
from pathlib import Path

from aggregator.database import Database
from aggregator.models import Listing


def listing(n: int, **overrides) -> Listing:
    base = dict(
        site="immoweb",
        site_listing_id=str(n),
        url=f"https://example.com/{n}",
        title=f"listing {n}",
        price=250_000,
    )
    base.update(overrides)
    return Listing(**base)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_new_returns_only_unseen(self):
        with Database(self.path) as db:
            first = db.add_new([listing(1), listing(2)])
            self.assertEqual({l.site_listing_id for l in first}, {"1", "2"})

            second = db.add_new([listing(2), listing(3)])
            self.assertEqual({l.site_listing_id for l in second}, {"3"})

            self.assertEqual(db.count(), 3)

    def test_state_persists_between_connections(self):
        with Database(self.path) as db:
            db.add_new([listing(1)])
        with Database(self.path) as db:
            self.assertTrue(db.is_known("immoweb:1"))
            self.assertEqual(db.add_new([listing(1)]), [])


def make_pair(**shared):
    """Те саме оголошення, ніби виставлене на двох різних сайтах."""
    fields = dict(
        transaction="rent", property_type="apartment",
        postal_code="9000", price=700, bedrooms=1, living_area=40,
    )
    fields.update(shared)
    a = Listing(site="immoweb", site_listing_id="a1", url="https://a.example/1",
                title="a", **fields)
    b = Listing(site="zimmo", site_listing_id="b1", url="https://b.example/1",
                title="b", **fields)
    return a, b


class CrossSiteDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_matching_listing_from_other_site_in_same_batch_is_suppressed(self):
        a, b = make_pair()
        with Database(self.path) as db:
            new_listings = db.add_new([a, b])
            to_notify, duplicates = db.split_cross_site_duplicates(new_listings)
            self.assertEqual([l.uid for l in to_notify], [a.uid])
            self.assertEqual([l.uid for l in duplicates], [b.uid])

    def test_matching_listing_from_other_site_in_later_run_is_suppressed(self):
        a, b = make_pair()
        with Database(self.path) as db:
            first_new = db.add_new([a])
            to_notify_1, dup_1 = db.split_cross_site_duplicates(first_new)
            self.assertEqual(to_notify_1, [a])
            self.assertEqual(dup_1, [])

            second_new = db.add_new([b])
            to_notify_2, dup_2 = db.split_cross_site_duplicates(second_new)
            self.assertEqual(to_notify_2, [])
            self.assertEqual([l.uid for l in dup_2], [b.uid])

    def test_different_price_is_not_treated_as_duplicate(self):
        a, b = make_pair()
        b = Listing(**{**b.__dict__, "price": 750})
        with Database(self.path) as db:
            new_listings = db.add_new([a, b])
            to_notify, duplicates = db.split_cross_site_duplicates(new_listings)
            self.assertEqual({l.uid for l in to_notify}, {a.uid, b.uid})
            self.assertEqual(duplicates, [])

    def test_mismatched_living_area_is_not_treated_as_duplicate(self):
        a, b = make_pair()
        b = Listing(**{**b.__dict__, "living_area": 90})
        with Database(self.path) as db:
            new_listings = db.add_new([a, b])
            to_notify, duplicates = db.split_cross_site_duplicates(new_listings)
            self.assertEqual({l.uid for l in to_notify}, {a.uid, b.uid})
            self.assertEqual(duplicates, [])

    def test_matching_listings_on_the_same_site_are_not_merged(self):
        fields = dict(
            transaction="rent", property_type="apartment",
            postal_code="9000", price=700, bedrooms=1, living_area=40,
        )
        a = Listing(site="immoweb", site_listing_id="a1", url="https://a.example/1", title="a", **fields)
        c = Listing(site="immoweb", site_listing_id="a2", url="https://a.example/2", title="c", **fields)
        with Database(self.path) as db:
            new_listings = db.add_new([a, c])
            to_notify, duplicates = db.split_cross_site_duplicates(new_listings)
            self.assertEqual({l.uid for l in to_notify}, {a.uid, c.uid})
            self.assertEqual(duplicates, [])


class FiberStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_address_returns_none(self):
        with Database(self.path) as db:
            self.assertIsNone(db.known_fiber_status("Kerkstraat", "1", "9000"))

    def test_update_and_read_back(self):
        a = listing(1, street="Kerkstraat", house_number="1", postal_code="9000")
        with Database(self.path) as db:
            db.add_new([a])
            db.update_fiber_info(a.uid, True, "FTTHBF")
            self.assertEqual(db.known_fiber_status("Kerkstraat", "1", "9000"), (True, "FTTHBF"))

    def test_second_listing_at_same_address_reuses_known_status(self):
        a = listing(1, street="Kerkstraat", house_number="1", postal_code="9000")
        b = listing(2, street="Kerkstraat", house_number="1", postal_code="9000")
        with Database(self.path) as db:
            db.add_new([a, b])
            db.update_fiber_info(a.uid, False, None)
            self.assertEqual(db.known_fiber_status("Kerkstraat", "1", "9000"), (False, None))

    def test_database_survives_upgrade_from_schema_without_new_columns(self):
        """
        Стара база (до появи duplicate_of/street/fiber_*) не мала цих
        стовпців. Переконуємось, що відкриття такої бази новою версією
        програми не падає, а сама додає стовпці, яких бракує.
        """
        import sqlite3

        conn = sqlite3.connect(self.path)
        conn.execute(
            """
            CREATE TABLE listings (
                uid TEXT PRIMARY KEY, site TEXT, site_listing_id TEXT, url TEXT,
                title TEXT, price REAL, currency TEXT, transaction_kind TEXT,
                property_type TEXT, bedrooms INTEGER, living_area REAL,
                locality TEXT, postal_code TEXT, first_seen_utc TEXT,
                notified INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

        with Database(self.path) as db:
            a = listing(1, street="Kerkstraat", house_number="1", postal_code="9000")
            db.add_new([a])
            db.update_fiber_info(a.uid, True, "FTTHBF")
            self.assertEqual(db.known_fiber_status("Kerkstraat", "1", "9000"), (True, "FTTHBF"))


if __name__ == "__main__":
    unittest.main()
