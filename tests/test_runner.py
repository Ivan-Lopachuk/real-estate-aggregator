"""Тести для aggregator/runner.py (лише формування посилання, без мережі)."""

import unittest

from aggregator.runner import _dashboard_link_for_batch


class DashboardLinkForBatchTests(unittest.TestCase):
    def test_appends_since_param(self):
        url = _dashboard_link_for_batch("https://example.github.io/board/", "2026-09-03T12:00:00+00:00")
        self.assertEqual(url, "https://example.github.io/board/?since=2026-09-03T12%3A00%3A00%2B00%3A00")

    def test_empty_page_url_stays_empty(self):
        self.assertEqual(_dashboard_link_for_batch("", "2026-09-03T12:00:00+00:00"), "")

    def test_appends_with_ampersand_if_url_already_has_query(self):
        url = _dashboard_link_for_batch("https://example.com/?x=1", "2026-01-01T00:00:00+00:00")
        self.assertTrue(url.startswith("https://example.com/?x=1&since="))


if __name__ == "__main__":
    unittest.main()
