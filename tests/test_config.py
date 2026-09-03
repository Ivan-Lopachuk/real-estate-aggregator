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


if __name__ == "__main__":
    unittest.main()
