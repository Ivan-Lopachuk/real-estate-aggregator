"""
Тести для aggregator/scrapers/zimmo.py.

Тут НЕ ходимо в інтернет (тести мають працювати без мережі й швидко).
Перевіряємо лише дві речі, які найлегше зламати випадковою зміною коду:
розбір вбудованого в HTML JSON-списку оголошень і перетворення одного
запису Zimmo на наш єдиний формат Listing.
"""

import unittest

from aggregator.config import HttpSettings, SearchCriteria
from aggregator.scrapers.zimmo import ZimmoScraper

# Скорочений, але справжній за формою фрагмент сторінки пошуку Zimmo:
# JS-виклик app.start({...}) із вбудованим масивом properties.
_SAMPLE_HTML = """
<script>
    $(function () {
        app.start({
            search: {"paging":{"from":0,"size":21}},
            properties: [{"code":"LRINC","uuid":"b155fe9b","type":"Appartement","prijs":"1010","slaapkamers":"2","b_woonopp":"61","gemeente":"Gent","postcode":"9000","address":"Sint-Lievenspoortstraat 77","url":"/nl/gent-9000/te-huur/appartement/LRINC/"},{"code":"","prijs":"500"}],
            save_search: false
        });
    });
</script>
"""


def make_scraper(**criteria_overrides) -> ZimmoScraper:
    criteria = SearchCriteria(**criteria_overrides)
    return ZimmoScraper(criteria, HttpSettings())


class ExtractPropertiesTests(unittest.TestCase):
    def test_extracts_array_from_embedded_app_start_call(self):
        items = ZimmoScraper._extract_properties(_SAMPLE_HTML)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["code"], "LRINC")

    def test_returns_empty_list_when_marker_missing(self):
        self.assertEqual(ZimmoScraper._extract_properties("<html>сторінка помилки</html>"), [])


class ToListingTests(unittest.TestCase):
    def test_converts_raw_item_to_listing(self):
        scraper = make_scraper(transaction="rent")
        items = ZimmoScraper._extract_properties(_SAMPLE_HTML)
        listing = scraper._to_listing(items[0], type_segment="appartement")

        self.assertEqual(listing.site, "zimmo")
        self.assertEqual(listing.site_listing_id, "LRINC")
        self.assertEqual(listing.url, "https://www.zimmo.be/nl/gent-9000/te-huur/appartement/LRINC/")
        self.assertEqual(listing.price, 1010.0)
        self.assertEqual(listing.bedrooms, 2)
        self.assertEqual(listing.living_area, 61.0)
        self.assertEqual(listing.locality, "Gent")
        self.assertEqual(listing.postal_code, "9000")
        self.assertEqual(listing.property_type, "apartment")
        self.assertEqual(listing.street, "Sint-Lievenspoortstraat")
        self.assertEqual(listing.house_number, "77")

    def test_item_without_code_is_skipped(self):
        scraper = make_scraper()
        items = ZimmoScraper._extract_properties(_SAMPLE_HTML)
        self.assertIsNone(scraper._to_listing(items[1], type_segment="appartement"))


class SplitAddressTests(unittest.TestCase):
    def test_splits_street_and_number(self):
        self.assertEqual(
            ZimmoScraper._split_address("Sint-Lievenspoortstraat 77"),
            ("Sint-Lievenspoortstraat", "77"),
        )

    def test_number_with_letter_suffix(self):
        self.assertEqual(ZimmoScraper._split_address("Kerkstraat 12A"), ("Kerkstraat", "12A"))

    def test_missing_address_returns_none_none(self):
        self.assertEqual(ZimmoScraper._split_address(None), (None, None))

    def test_address_without_number_kept_as_street(self):
        self.assertEqual(ZimmoScraper._split_address("Grote Markt"), ("Grote Markt", None))


if __name__ == "__main__":
    unittest.main()
