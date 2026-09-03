"""Тести для aggregator/notifier.py (лише формування тексту, без SMTP)."""

import unittest

from aggregator.models import Listing
from aggregator.notifier import build_body, build_short_body


def make_listing(n: int) -> Listing:
    return Listing(
        site="immoweb", site_listing_id=str(n), url=f"https://example.com/{n}",
        title=f"listing {n}", price=700,
    )


class BuildShortBodyTests(unittest.TestCase):
    def test_with_page_url_hides_individual_listings(self):
        listings = [make_listing(1), make_listing(2)]
        body = build_short_body(listings, "https://example.github.io/board/")
        self.assertIn("2", body)
        self.assertIn("https://example.github.io/board/", body)
        self.assertNotIn("https://example.com/1", body)
        self.assertNotIn("https://example.com/2", body)

    def test_without_page_url_falls_back_to_full_list(self):
        listings = [make_listing(1)]
        body = build_short_body(listings, "")
        self.assertEqual(body, build_body(listings, ""))
        self.assertIn("https://example.com/1", body)


if __name__ == "__main__":
    unittest.main()
