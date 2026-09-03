"""Тести для aggregator/config.py -- SearchCriteria.summary."""

import unittest

from aggregator.config import SearchCriteria


class SearchCriteriaSummaryTests(unittest.TestCase):
    def test_shows_postal_codes_when_localities_not_set(self):
        s = SearchCriteria(transaction="rent", postal_codes=["9000", "8500"])
        self.assertIn("9000, 8500", s.summary)

    def test_prefers_localities_over_postal_codes_when_both_set(self):
        s = SearchCriteria(
            transaction="rent", postal_codes=["9000", "8500"],
            localities=["Gent", "Kortrijk"],
        )
        self.assertIn("Gent, Kortrijk", s.summary)
        self.assertNotIn("9000", s.summary)

    def test_shows_neither_when_both_empty(self):
        s = SearchCriteria(transaction="sale")
        self.assertNotIn(",", s.summary)

    def test_price_max_only_shows_do_not_ellipsis(self):
        s = SearchCriteria(transaction="rent", price_max=1000)
        self.assertIn("до 1 000 €", s.summary)
        self.assertNotIn("…", s.summary)

    def test_price_min_only_shows_vid_not_ellipsis(self):
        s = SearchCriteria(transaction="rent", price_min=600)
        self.assertIn("від 600 €", s.summary)
        self.assertNotIn("…", s.summary)

    def test_bedrooms_min_only_shows_vid_not_ellipsis(self):
        s = SearchCriteria(transaction="rent", bedrooms_min=2)
        self.assertIn("від 2 спалень", s.summary)
        self.assertNotIn("…", s.summary)


if __name__ == "__main__":
    unittest.main()
