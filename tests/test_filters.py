"""
Тести фільтрації. Запуск:  python -m unittest

Використовує лише стандартну бібліотеку (unittest), тож нічого
додатково встановлювати не треба.
"""

import unittest

from aggregator.config import SearchCriteria
from aggregator.filters import ListingFilter
from aggregator.models import Listing


def make_listing(**overrides) -> Listing:
    base = dict(
        site="immoweb",
        site_listing_id="1",
        url="https://example.com/1",
        title="test",
        price=300_000,
        property_type="house",
        bedrooms=3,
        living_area=120,
        locality="Gent",
        postal_code="9000",
    )
    base.update(overrides)
    return Listing(**base)


class FilterTests(unittest.TestCase):
    def test_price_out_of_range_is_rejected(self):
        f = ListingFilter(SearchCriteria(price_min=200_000, price_max=350_000))
        self.assertTrue(f.matches(make_listing(price=300_000)))
        self.assertFalse(f.matches(make_listing(price=400_000)))
        self.assertFalse(f.matches(make_listing(price=100_000)))

    def test_missing_value_is_not_rejected(self):
        f = ListingFilter(SearchCriteria(price_max=350_000, living_area_min=90))
        self.assertTrue(f.matches(make_listing(price=None, living_area=None)))

    def test_property_type_filter(self):
        f = ListingFilter(SearchCriteria(property_types=["apartment"]))
        self.assertFalse(f.matches(make_listing(property_type="house")))
        self.assertTrue(f.matches(make_listing(property_type="apartment")))

    def test_postal_code_filter(self):
        f = ListingFilter(SearchCriteria(postal_codes=["9000", "9040"]))
        self.assertTrue(f.matches(make_listing(postal_code="9040")))
        self.assertFalse(f.matches(make_listing(postal_code="1000")))

    def test_locality_substring_filter_is_case_insensitive(self):
        f = ListingFilter(SearchCriteria(localities=["gent"]))
        self.assertTrue(f.matches(make_listing(locality="Sint-Amandsberg (Gent)")))
        self.assertFalse(f.matches(make_listing(locality="Brugge")))

    def test_bedrooms_range(self):
        f = ListingFilter(SearchCriteria(bedrooms_min=2, bedrooms_max=4))
        self.assertTrue(f.matches(make_listing(bedrooms=3)))
        self.assertFalse(f.matches(make_listing(bedrooms=1)))
        self.assertFalse(f.matches(make_listing(bedrooms=5)))


if __name__ == "__main__":
    unittest.main()
