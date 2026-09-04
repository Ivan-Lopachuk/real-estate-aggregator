"""
Тести для aggregator/scrapers/immovlan.py.

Тут НЕ ходимо в інтернет — розбираємо власний, невеликий, вигаданий
шматок HTML у тому самому вигляді, що й справжня картка оголошення
на сторінці результатів пошуку Immovlan (`<article class="v3-search-
card">`), і перевіряємо лише логіку перетворення в Listing.
"""

import unittest

from bs4 import BeautifulSoup

from aggregator.config import HttpSettings, SearchCriteria
from aggregator.scrapers.immovlan import ImmovlanScraper


def _card(html: str):
    return BeautifulSoup(html, "html.parser").select_one("article")


_FULL_CARD = """
<article class="v3-search-card" data-url="https://immovlan.be/en/detail/apartment/for-rent/9000/gent/rwc43339">
    <img class="lazyload" data-src="https://api-image.immovlan.be/v1/property/RWC43339/thumbnail-webp/Medium?h=280" />
    <span class="v3-search-card-price">799&#x202F;&#x20AC;</span>
    <p itemprop="address">
        <span itemprop="postalCode">9000</span>
        <span itemprop="addressLocality">Gent</span>
    </p>
    <div class="v3-search-card-highlights">
        <span class="v3-search-card-pill"><strong>1</strong> Bedroom(s)</span>
        <span class="v3-search-card-pill"><strong>48</strong> m&#xB2;</span>
        <span class="v3-search-card-pill"><strong>1</strong> Bathroom(s)</span>
    </div>
</article>
"""

_MINIMAL_CARD = """
<article class="v3-search-card" data-url="https://immovlan.be/en/detail/residence/for-rent/8500/kortrijk/rbw1/">
</article>
"""


def _scraper(**criteria_kwargs) -> ImmovlanScraper:
    criteria = SearchCriteria(
        transaction=criteria_kwargs.pop("transaction", "rent"),
        property_types=criteria_kwargs.pop("property_types", ["house", "apartment"]),
        **criteria_kwargs,
    )
    return ImmovlanScraper(criteria, HttpSettings())


class ToListingTests(unittest.TestCase):
    def test_parses_full_card(self):
        listing = _scraper()._to_listing(_card(_FULL_CARD), "apartment")

        self.assertEqual(listing.site, "immovlan")
        self.assertEqual(listing.site_listing_id, "rwc43339")
        self.assertEqual(listing.url, "https://immovlan.be/en/detail/apartment/for-rent/9000/gent/rwc43339")
        self.assertEqual(listing.price, 799.0)
        self.assertEqual(listing.postal_code, "9000")
        self.assertEqual(listing.locality, "Gent")
        self.assertEqual(listing.bedrooms, 1)
        self.assertEqual(listing.living_area, 48.0)
        self.assertEqual(listing.property_type, "apartment")
        self.assertEqual(
            listing.photo_url,
            "https://api-image.immovlan.be/v1/property/RWC43339/thumbnail-webp/Medium?h=280",
        )

    def test_bathroom_pill_does_not_get_read_as_bedrooms_or_area(self):
        listing = _scraper()._to_listing(_card(_FULL_CARD), "apartment")
        # "1 Bathroom(s)" не мало б перетерти вже знайдені bedrooms/living_area.
        self.assertEqual(listing.bedrooms, 1)
        self.assertEqual(listing.living_area, 48.0)

    def test_terrace_area_pill_is_not_mistaken_for_living_area(self):
        html = _FULL_CARD.replace(
            '<span class="v3-search-card-pill"><strong>1</strong> Bathroom(s)</span>',
            '<span class="v3-search-card-pill"><strong>20</strong> m&#xB2; Terrace</span>',
        )
        listing = _scraper()._to_listing(_card(html), "apartment")
        self.assertEqual(listing.living_area, 48.0)

    def test_missing_optional_fields_do_not_crash(self):
        listing = _scraper()._to_listing(_card(_MINIMAL_CARD), "house")

        self.assertEqual(listing.site_listing_id, "rbw1")
        self.assertIsNone(listing.price)
        self.assertIsNone(listing.postal_code)
        self.assertIsNone(listing.locality)
        self.assertIsNone(listing.bedrooms)
        self.assertIsNone(listing.living_area)
        self.assertIsNone(listing.photo_url)

    def test_card_without_data_url_is_skipped(self):
        card = _card('<article class="v3-search-card"></article>')
        self.assertIsNone(_scraper()._to_listing(card, "house"))


class PropertyTypesTests(unittest.TestCase):
    def test_defaults_to_both_when_criteria_has_neither(self):
        scraper = _scraper(property_types=["studio"])  # ані house, ані apartment
        self.assertEqual(scraper._property_types(), ["house", "apartment"])

    def test_filters_to_requested_types_only(self):
        scraper = _scraper(property_types=["apartment"])
        self.assertEqual(scraper._property_types(), ["apartment"])


if __name__ == "__main__":
    unittest.main()
