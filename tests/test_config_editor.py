"""
Тести для aggregator/config_editor.py.

Перевіряємо на копії справжньої структури config.yaml: після точкової
заміни (1) змінені поля справді нові, (2) усе інше — коментарі, інші
розділи, форматування — лишається байт-у-байт таким самим, (3) файл і
далі коректно завантажується через aggregator.config.Config.load.
"""

import tempfile
import unittest
from pathlib import Path

from aggregator.config import Config
from aggregator.config_editor import CriteriaUpdateError, update_search_criteria

_SAMPLE_CONFIG = """\
# ============================================================
#  Real Estate Aggregator — файл налаштувань
# ============================================================

sites:
  - immoweb
  - zimmo

# ----- Що саме шукаємо ---------------------------------------
search:
  # "sale" — купівля, "rent" — оренда
  transaction: rent

  # Типи житла. Можливі варіанти: house, apartment
  property_types:
    - house
    - apartment

  # Діапазон ціни в євро. null = без обмеження.
  price_min: 600
  price_max: 800

  # Кількість спалень. null = без обмеження.
  bedrooms_min: 1
  bedrooms_max: 1

  # Мінімальна житлова площа в м². null = без обмеження.
  living_area_min: 35

  # Бельгійські поштові індекси (як текст, у лапках).
  postal_codes:
    - "9000"   # Gent
    - "8500"   # Kortrijk

  # Необов'язково: залишати лише оголошення, у назві населеного пункту.
  localities: []

# ----- Як часто перевіряти -----
poll:
  interval_minutes: 360

database:
  path: listings.db

http:
  request_delay_seconds: 1.0
  max_pages: 10
  timeout_seconds: 20

notifications:
  method: console
"""


class UpdateSearchCriteriaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.yaml"
        self.path.write_text(_SAMPLE_CONFIG, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_fields_given_returns_false_and_leaves_file_untouched(self):
        changed = update_search_criteria(self.path)
        self.assertFalse(changed)
        self.assertEqual(self.path.read_text(encoding="utf-8"), _SAMPLE_CONFIG)

    def test_scalar_field_is_replaced_in_place(self):
        changed = update_search_criteria(self.path, price_max=900)
        self.assertTrue(changed)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("  price_max: 900\n", text)
        # Сусіднє поле й усе інше не чіпається.
        self.assertIn("  price_min: 600\n", text)
        self.assertIn('# "sale" — купівля, "rent" — оренда', text)

    def test_scalar_field_can_be_cleared_to_null(self):
        update_search_criteria(self.path, price_max=None)
        self.assertIn("  price_max: null\n", self.path.read_text(encoding="utf-8"))

    def test_float_that_is_whole_number_renders_without_trailing_zero(self):
        update_search_criteria(self.path, living_area_min=40.0)
        self.assertIn("  living_area_min: 40\n", self.path.read_text(encoding="utf-8"))

    def test_list_field_is_replaced_wholesale(self):
        update_search_criteria(self.path, postal_codes=["1000"])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('  postal_codes:\n    - "1000"\n', text)
        self.assertNotIn("9000", text)
        self.assertNotIn("Kortrijk", text)  # старий inline-коментар зник разом зі старим значенням

    def test_empty_list_renders_as_inline_brackets(self):
        update_search_criteria(self.path, postal_codes=[])
        self.assertIn("  postal_codes: []\n", self.path.read_text(encoding="utf-8"))

    def test_property_types_unquoted_items(self):
        update_search_criteria(self.path, property_types=["house"])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("  property_types:\n    - house\n", text)
        self.assertNotIn("    - apartment\n", text)

    def test_unrelated_sections_are_byte_identical_after_update(self):
        update_search_criteria(self.path, price_min=500, transaction="sale")
        text = self.path.read_text(encoding="utf-8")
        for untouched_line in (
            "database:\n", "  path: listings.db\n",
            "http:\n", "  max_pages: 10\n",
            "notifications:\n", "  method: console\n",
        ):
            self.assertIn(untouched_line, text)

    def test_result_still_loads_via_config_load(self):
        update_search_criteria(
            self.path,
            transaction="sale",
            property_types=["apartment"],
            price_min=None,
            price_max=500000,
            postal_codes=["9000"],
        )
        config = Config.load(self.path)
        self.assertEqual(config.search.transaction, "sale")
        self.assertEqual(config.search.property_types, ["apartment"])
        self.assertIsNone(config.search.price_min)
        self.assertEqual(config.search.price_max, 500000)
        self.assertEqual(config.search.postal_codes, ["9000"])

    def test_missing_key_raises_clear_error(self):
        broken = Path(self.tmp.name) / "broken.yaml"
        broken.write_text("search:\n  transaction: rent\n", encoding="utf-8")
        with self.assertRaises(CriteriaUpdateError):
            update_search_criteria(broken, price_min=100)


if __name__ == "__main__":
    unittest.main()
