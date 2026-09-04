"""Тести для aggregator/notifier.py (лише формування тексту, без SMTP)."""

import unittest

from aggregator.models import Listing
from aggregator.notifier import _format_listing, build_body, build_short_body, build_short_html


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


class BuildShortHtmlTests(unittest.TestCase):
    def test_empty_without_page_url(self):
        self.assertEqual(build_short_html([make_listing(1)], ""), "")

    def test_link_text_is_short_phrase_not_the_raw_url(self):
        # Саме заради цього й існує HTML-версія: довгий ?ids=... URL має
        # лежати лише в атрибуті href, а видимий текст посилання —
        # короткою фразою, а не самим URL (у plain-тексті build_short_body
        # він і далі повністю видимий — HTML лише альтернатива для
        # клієнтів, що вміють її показати).
        long_url = "https://example.github.io/board/?ids=" + ",".join(f"immoweb:{i}" for i in range(50))
        out = build_short_html([make_listing(1)], long_url)
        self.assertIn(f'href="{long_url}"', out)
        # Видимий текст посилання — те, що між ">" і "</a>" — короткий,
        # без сліду самого URL усередині.
        link_text = out.split("</a>")[0].rsplit(">", 1)[-1]
        self.assertEqual(link_text, "Переглянути на дошці →")
        self.assertNotIn("ids=", link_text)

    def test_url_is_html_escaped_in_href(self):
        out = build_short_html([make_listing(1)], "https://example.github.io/board/?a=1&b=2")
        self.assertIn('href="https://example.github.io/board/?a=1&amp;b=2"', out)

    def test_count_is_included(self):
        out = build_short_html([make_listing(1), make_listing(2)], "https://example.github.io/board/")
        self.assertIn("2", out)


class FormatListingExtraCostsTests(unittest.TestCase):
    def test_shows_extra_costs_when_present(self):
        l = Listing(site="immoweb", site_listing_id="1", url="https://example.com/1",
                     title="Apartment", price=750, extra_costs=160)
        self.assertIn("750 EUR (+ 160 EUR)", _format_listing(l))

    def test_hides_extra_costs_when_absent(self):
        l = Listing(site="immoweb", site_listing_id="1", url="https://example.com/1",
                     title="Apartment", price=750)
        self.assertNotIn("+", _format_listing(l))


if __name__ == "__main__":
    unittest.main()
