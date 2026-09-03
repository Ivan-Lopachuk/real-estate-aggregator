"""
Опис одного оголошення про нерухомість.

`Listing` — це простий контейнер даних (dataclass). Кожен scraper
перетворює «сиру» відповідь свого сайту на список таких об'єктів, тож
решта програми (фільтри, база даних, сповіщення) працює з єдиним
форматом і не знає, з якого сайту прийшли дані.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Listing:
    # --- обов'язкові поля ---
    site: str                       # назва сайту-джерела, напр. "immoweb"
    site_listing_id: str            # ідентифікатор оголошення В МЕЖАХ цього сайту
    url: str                        # посилання на сторінку оголошення
    title: str                      # короткий людський опис

    # --- необов'язкові поля (None, якщо сайт їх не дав) ---
    price: Optional[float] = None
    extra_costs: Optional[float] = None     # комунальні/додаткові витрати (якщо сайт вказує окремо)
    currency: str = "EUR"
    transaction: Optional[str] = None      # "sale" або "rent"
    property_type: Optional[str] = None    # "house", "apartment", ...
    bedrooms: Optional[int] = None
    living_area: Optional[float] = None     # м²
    locality: Optional[str] = None          # назва населеного пункту
    postal_code: Optional[str] = None
    street: Optional[str] = None            # назва вулиці (якщо сайт її дає)
    house_number: Optional[str] = None      # номер будинку
    photo_url: Optional[str] = None         # адреса головного фото оголошення
    listed_at: Optional[str] = None         # коли сайт виставив/оновив оголошення (ISO, UTC)

    # Повна сира відповідь сайту — на випадок, якщо колись знадобляться
    # додаткові поля. `repr=False`, щоб не засмічувати вивід у консолі.
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def uid(self) -> str:
        """
        Глобально унікальний ключ оголошення: назва сайту + його id.
        Саме за ним база даних розрізняє «нове» і «вже бачене».
        """
        return f"{self.site}:{self.site_listing_id}"
