"""
Тести для scripts/apply_search_criteria.py.

Скрипт лежить поза пакетом aggregator (у scripts/), тож імпортуємо його
напряму за шляхом до файлу — так само, як це робить сам скрипт для
aggregator/.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "apply_search_criteria.py"
_spec = importlib.util.spec_from_file_location("apply_search_criteria", _SCRIPT_PATH)
apply_search_criteria = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = apply_search_criteria
_spec.loader.exec_module(apply_search_criteria)

_SAMPLE_CONFIG = """\
sites:
  - immoweb

search:
  transaction: rent
  property_types:
    - house
    - apartment
  price_min: 600
  price_max: 800
  bedrooms_min: 1
  bedrooms_max: 1
  living_area_min: 35
  postal_codes:
    - "9000"
  localities: []

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


class ParsingHelperTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = dict(__import__("os").environ)

    def tearDown(self):
        import os
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _set(self, **env):
        import os
        for key, value in env.items():
            os.environ[key] = value

    def test_empty_env_means_unset(self):
        self.assertIs(apply_search_criteria._text_or_unset("CRITERIA_DOES_NOT_EXIST"), apply_search_criteria.UNSET)

    def test_null_word_means_clear(self):
        self._set(CRITERIA_PRICE_MIN="null")
        self.assertIsNone(apply_search_criteria._number_or_unset("CRITERIA_PRICE_MIN", float))

    def test_number_is_parsed(self):
        self._set(CRITERIA_PRICE_MIN="650")
        self.assertEqual(apply_search_criteria._number_or_unset("CRITERIA_PRICE_MIN", float), 650.0)

    def test_invalid_number_raises_system_exit(self):
        self._set(CRITERIA_PRICE_MIN="not-a-number")
        with self.assertRaises(SystemExit):
            apply_search_criteria._number_or_unset("CRITERIA_PRICE_MIN", float)

    def test_list_is_split_and_trimmed(self):
        self._set(CRITERIA_POSTAL_CODES="9000, 8500 ,  ")
        self.assertEqual(apply_search_criteria._list_or_unset("CRITERIA_POSTAL_CODES"), ["9000", "8500"])

    def test_property_types_combo_choice(self):
        self._set(CRITERIA_PROPERTY_TYPES="house та apartment")
        self.assertEqual(apply_search_criteria._property_types_or_unset(), ["house", "apartment"])

    def test_property_types_default_choice_is_unset(self):
        self._set(CRITERIA_PROPERTY_TYPES="(без змін)")
        self.assertIs(apply_search_criteria._property_types_or_unset(), apply_search_criteria.UNSET)


class MainEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.yaml"
        self.path.write_text(_SAMPLE_CONFIG, encoding="utf-8")
        self._env_backup = dict(__import__("os").environ)

    def tearDown(self):
        import os
        os.environ.clear()
        os.environ.update(self._env_backup)
        self.tmp.cleanup()

    def test_updates_price_and_leaves_rest_untouched(self):
        import os
        os.environ["CRITERIA_PRICE_MAX"] = "900"
        code = apply_search_criteria.main(["--config", str(self.path)])
        self.assertEqual(code, 0)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("  price_max: 900\n", text)
        self.assertIn("  price_min: 600\n", text)

    def test_no_env_vars_is_a_no_op(self):
        before = self.path.read_text(encoding="utf-8")
        code = apply_search_criteria.main(["--config", str(self.path)])
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
