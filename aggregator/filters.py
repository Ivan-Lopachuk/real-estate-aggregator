"""
Фільтрація оголошень за критеріями з config.yaml.

Навіщо окремий фільтр, якщо scraper і так передає сайту параметри пошуку?
Тому що параметри в URL — це «груба» фільтрація на боці сайту, якій не
можна повністю довіряти (сайт може віддати трохи зайвого, назви полів
змінюються). Цей модуль — «точна» перевірка вже в нас, на боці програми.

Важливе правило: якщо в оголошення БРАКУЄ якогось поля (напр. ціни),
ми його НЕ відкидаємо — бракує даних не означає «не підходить».
"""

from __future__ import annotations

import logging
from typing import Iterable

from .config import SearchCriteria
from .models import Listing

log = logging.getLogger(__name__)


class ListingFilter:
    def __init__(self, criteria: SearchCriteria) -> None:
        self.c = criteria

    def matches(self, listing: Listing) -> bool:
        """True, якщо оголошення відповідає всім заданим критеріям."""
        c = self.c

        if listing.price is not None:
            if c.price_min is not None and listing.price < c.price_min:
                return False
            if c.price_max is not None and listing.price > c.price_max:
                return False

        if listing.bedrooms is not None:
            if c.bedrooms_min is not None and listing.bedrooms < c.bedrooms_min:
                return False
            if c.bedrooms_max is not None and listing.bedrooms > c.bedrooms_max:
                return False

        if (
            listing.living_area is not None
            and c.living_area_min is not None
            and listing.living_area < c.living_area_min
        ):
            return False

        if c.property_types and listing.property_type is not None:
            allowed = {t.lower() for t in c.property_types}
            if listing.property_type.lower() not in allowed:
                return False

        if c.postal_codes and listing.postal_code is not None:
            if listing.postal_code not in set(c.postal_codes):
                return False

        if c.localities and listing.locality is not None:
            name = listing.locality.lower()
            if not any(term.lower() in name for term in c.localities):
                return False

        return True

    def apply(self, listings: Iterable[Listing]) -> list[Listing]:
        kept = [l for l in listings if self.matches(l)]
        return kept
