"""
Тести для aggregator/proximus.py.

Тут НЕ ходимо в інтернет: перевіряємо лише, що функція коректно
відмовляється робити запит, коли вхідних даних не досить (немає вулиці,
номера будинку чи поштового індексу) — це найлегше зламати випадково.
Сам виклик до proximus.be (мережевий) тестами не покривається.
"""

import unittest

from aggregator.proximus import check_fiber


class CheckFiberGuardTests(unittest.TestCase):
    def test_returns_none_without_street(self):
        self.assertIsNone(check_fiber(None, "74", "9000", "Gent"))

    def test_returns_none_without_house_number(self):
        self.assertIsNone(check_fiber("Blankenbergestraat", None, "9000", "Gent"))

    def test_returns_none_without_postal_code(self):
        self.assertIsNone(check_fiber("Blankenbergestraat", "74", None, "Gent"))


if __name__ == "__main__":
    unittest.main()
