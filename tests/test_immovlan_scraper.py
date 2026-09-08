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
from aggregator.scrapers.immovlan import (
    ImmovlanScraper,
    _split_street_and_number,
)


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


# Сторінка оголошення: schema.org JSON-LD, як у справжньому Immovlan.
# Адреса самої нерухомості — у mainEntity.address; адреса агентства
# (offers.offeredBy.address) НЕ має плутатися з нею.
_DETAIL_PAGE = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "RealEstateListing",
  "mainEntity": {
    "@type": "Apartment",
    "address": {"@type": "PostalAddress", "streetAddress": "Oudenaardsesteenweg 20",
                "addressLocality": "Kortrijk", "postalCode": "8500"},
    "geo": {"@type": "GeoCoordinates", "latitude": 50.82, "longitude": 3.27}
  },
  "offers": {
    "@type": "Offer",
    "offeredBy": {"@type": "RealEstateAgent", "name": "Immo Test",
      "address": {"@type": "PostalAddress", "streetAddress": "Veemarkt 53"}}
  }
}
</script>
</head><body></body></html>
"""

# Оголошення знято — Immovlan віддає список інших квартир, без адреси.
_DETAIL_PAGE_GONE = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "ItemList",
 "itemListElement": [{"@type": "ListItem", "item": {"@type": "RealEstateListing",
   "mainEntity": {"@type": "Apartment",
     "address": {"@type": "PostalAddress", "addressLocality": "Kortrijk", "postalCode": "8500"}}}}]}
</script>
</head><body></body></html>
"""


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeSession:
    """
    Підміняє self.session — рахує запити, віддає заготовлений HTML.
    `pages` — або один рядок на всі URL, або словник {url: html}.
    """

    def __init__(self, pages):
        self._pages = pages
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        if isinstance(self._pages, dict):
            return _FakeResponse(self._pages.get(url, "<html></html>"))
        return _FakeResponse(self._pages)


class SplitStreetAndNumberTests(unittest.TestCase):
    def test_plain_street_and_number(self):
        self.assertEqual(_split_street_and_number("Kerkstraat 12"), ("Kerkstraat", "12"))

    def test_multiword_street(self):
        self.assertEqual(
            _split_street_and_number("Sint-Denijssestraat 171"), ("Sint-Denijssestraat", "171")
        )

    def test_box_number_after_house_number_is_dropped(self):
        self.assertEqual(_split_street_and_number("Paleisstraat 3 0031"), ("Paleisstraat", "3"))

    def test_slash_box_is_dropped(self):
        self.assertEqual(
            _split_street_and_number("Raveschootstraat 2/201"), ("Raveschootstraat", "2")
        )

    def test_number_with_letter(self):
        self.assertEqual(
            _split_street_and_number("Avenue des Villas 12A"), ("Avenue des Villas", "12A")
        )

    def test_street_without_number(self):
        self.assertEqual(_split_street_and_number("Grote Markt"), ("Grote Markt", None))


class ParseDetailAddressTests(unittest.TestCase):
    def test_reads_property_address_not_agency_address(self):
        street, number = ImmovlanScraper._parse_detail_address(_DETAIL_PAGE)
        self.assertEqual((street, number), ("Oudenaardsesteenweg", "20"))

    def test_withdrawn_listing_yields_no_address(self):
        self.assertEqual(
            ImmovlanScraper._parse_detail_address(_DETAIL_PAGE_GONE), (None, None)
        )

    def test_garbage_html_yields_no_address(self):
        self.assertEqual(ImmovlanScraper._parse_detail_address("<html></html>"), (None, None))


class WithExactAddressTests(unittest.TestCase):
    def _listing(self):
        return _scraper()._to_listing(_card(_FULL_CARD), "apartment")

    def test_fills_street_and_number_from_detail_page(self):
        scraper = _scraper()
        scraper.http = HttpSettings(request_delay_seconds=0)
        scraper.session = _FakeSession(_DETAIL_PAGE)
        scraper._detail_lookups = 0

        enriched = scraper._with_exact_address(self._listing())
        self.assertEqual(enriched.street, "Oudenaardsesteenweg")
        self.assertEqual(enriched.house_number, "20")

    def test_stops_making_requests_once_limit_reached(self):
        scraper = _scraper()
        scraper.http = HttpSettings(request_delay_seconds=0)
        scraper.session = _FakeSession(_DETAIL_PAGE)
        scraper._detail_lookups = 10_000  # ліміт уже вичерпано

        listing = self._listing()
        result = scraper._with_exact_address(listing)
        self.assertEqual(scraper.session.calls, 0)
        self.assertIs(result, listing)


class AddressesForUrlsTests(unittest.TestCase):
    def test_returns_addresses_only_for_pages_that_have_one(self):
        scraper = _scraper()
        scraper.http = HttpSettings(request_delay_seconds=0)
        scraper.session = _FakeSession({
            "https://immovlan.be/en/detail/x/1": _DETAIL_PAGE,
            "https://immovlan.be/en/detail/x/2": _DETAIL_PAGE_GONE,
        })

        found = scraper.addresses_for_urls([
            "https://immovlan.be/en/detail/x/1",
            "https://immovlan.be/en/detail/x/2",
        ])
        self.assertEqual(
            found, {"https://immovlan.be/en/detail/x/1": ("Oudenaardsesteenweg", "20")}
        )


class PropertyTypesTests(unittest.TestCase):
    def test_defaults_to_both_when_criteria_has_neither(self):
        scraper = _scraper(property_types=["studio"])  # ані house, ані apartment
        self.assertEqual(scraper._property_types(), ["house", "apartment"])

    def test_filters_to_requested_types_only(self):
        scraper = _scraper(property_types=["apartment"])
        self.assertEqual(scraper._property_types(), ["apartment"])


if __name__ == "__main__":
    unittest.main()
