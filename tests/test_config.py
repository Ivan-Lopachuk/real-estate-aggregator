"""Тести для aggregator/config.py -- SearchCriteria.summary та розбір каналів сповіщень."""

import unittest

from aggregator.config import SearchCriteria, parse_notification_methods


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


class ParseNotificationMethodsTests(unittest.TestCase):
    def test_both_means_console_and_email(self):
        self.assertEqual(parse_notification_methods("both"), {"console", "email"})

    def test_single_method(self):
        self.assertEqual(parse_notification_methods("telegram"), {"telegram"})

    def test_comma_separated_combo(self):
        self.assertEqual(parse_notification_methods("email,telegram"), {"email", "telegram"})

    def test_whitespace_around_tokens_is_ignored(self):
        self.assertEqual(parse_notification_methods(" email , telegram "), {"email", "telegram"})


if __name__ == "__main__":
    unittest.main()
