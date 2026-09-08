"""
Тести для aggregator/geocoding.py.

Тут НЕ ходимо в інтернет — передаємо власний, невеликий, вигаданий
список `places` у тому самому форматі, що повертає geo-api.zimmo.be,
і перевіряємо лише логіку пошуку по ньому.
"""

import unittest

from aggregator.geocoding import postal_codes_for_name, slugs_for_postal_codes

_PLACES = [
    {
        "translations": {"nl": "Gent"},
        "slugs": {"nl": "gent"},
        "administrativeArea": {"postalCode": "9000", "slug": "gent"},
    },
    {
        "translations": {"nl": "Gentinnes"},
        "slugs": {"nl": "gentinnes"},
        "administrativeArea": {"postalCode": "1450", "slug": "gentinnes"},
    },
    {
        "translations": {"nl": "Kortrijk"},
        "aliases": [{"locale": "fr", "name": "Courtrai"}],
        "slugs": {"nl": "kortrijk"},
        "administrativeArea": {"postalCode": "8500", "slug": "kortrijk"},
    },
    {
        "translations": {"nl": "Merksem"},
        "slugs": {"nl": "merksem"},
        "administrativeArea": {"postalCode": "2170", "slug": "merksem"},
    },
    # Немає жодного відомого імені — має просто ігноруватись.
    {"translations": {}, "administrativeArea": {"postalCode": "0000"}},
]


class PostalCodesForNameTests(unittest.TestCase):
    def test_exact_match_wins_over_substring_matches(self):
        # "Gent" не має плутатись із "Gentinnes", хоч та й містить підрядок.
        self.assertEqual(postal_codes_for_name("Gent", _PLACES), ["9000"])

    def test_case_insensitive(self):
        self.assertEqual(postal_codes_for_name("GENT", _PLACES), ["9000"])

    def test_matches_alias_name(self):
        self.assertEqual(postal_codes_for_name("Courtrai", _PLACES), ["8500"])

    def test_falls_back_to_substring_when_no_exact_match(self):
        result = postal_codes_for_name("Merkse", _PLACES)
        self.assertEqual(result, ["2170"])

    def test_unknown_place_returns_empty(self):
        self.assertEqual(postal_codes_for_name("Антарктида", _PLACES), [])

    def test_empty_text_returns_empty(self):
        self.assertEqual(postal_codes_for_name("   ", _PLACES), [])

    def test_ukrainian_name_resolves_via_alias(self):
        self.assertEqual(postal_codes_for_name("Гент", _PLACES), ["9000"])

    def test_ukrainian_name_is_case_insensitive(self):
        self.assertEqual(postal_codes_for_name("гент", _PLACES), ["9000"])

    def test_ukrainian_name_with_surrounding_whitespace(self):
        self.assertEqual(postal_codes_for_name("  Мерксем  ", _PLACES), ["2170"])


class SlugsForPostalCodesTests(unittest.TestCase):
    def test_builds_slug_with_postal_code_suffix(self):
        slugs, found = slugs_for_postal_codes(["9000", "8500"], _PLACES)
        self.assertEqual(set(slugs), {"gent-9000", "kortrijk-8500"})
        self.assertEqual(found, {"9000", "8500"})

    def test_missing_postal_code_is_reported_but_others_still_found(self):
        slugs, found = slugs_for_postal_codes(["9000", "9999"], _PLACES)
        self.assertEqual(slugs, ["gent-9000"])
        self.assertEqual(found, {"9000"})


if __name__ == "__main__":
    unittest.main()
