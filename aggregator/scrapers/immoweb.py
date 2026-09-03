"""
Scraper для Immoweb.be — першого (і поки що єдиного) сайту.

ЧОМУ JSON API, а не парсинг HTML
--------------------------------
Сторінка пошуку на immoweb.be звертається до тієї самої адреси, яку ви
бачите в рядку браузера, але якщо надіслати запит із заголовком
`Accept: application/json`, сервер відповідає структурованим JSON, а не
HTML-розміткою. Приклад адреси:

    https://www.immoweb.be/en/search-results/house-and-apartment/for-sale
        ?countries=BE&page=1&orderBy=newest&minPrice=200000&maxPrice=400000

У відповіді є список `results`, де кожен елемент описує одну нерухомість
(поля `id`, `property`, `transaction`, `price`). Це набагато стабільніше
за читання HTML, який на сайті часто змінюється.

Сторінка конкретного оголошення: https://www.immoweb.be/en/classified/<id>
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

from ..models import Listing
from .base import BaseScraper, register

log = logging.getLogger(__name__)

# Наші прості назви типів  ->  значення в API Immoweb і навпаки.
_API_TYPE_TO_SIMPLE = {"HOUSE": "house", "APARTMENT": "apartment"}


@register
class ImmowebScraper(BaseScraper):
    site_name = "immoweb"

    _SEARCH_URL = "https://www.immoweb.be/en/search-results/{path}/{transaction}"
    _CLASSIFIED_URL = "https://www.immoweb.be/en/classified/{id}"

    # -- побудова запиту --------------------------------------------

    def _path_segment(self) -> str:
        """Частина URL, що позначає тип житла."""
        types = {t.lower() for t in self.criteria.property_types}
        if types == {"house"}:
            return "house"
        if types == {"apartment"}:
            return "apartment"
        return "house-and-apartment"

    def _transaction_segment(self) -> str:
        return "for-rent" if self.criteria.transaction == "rent" else "for-sale"

    def _params(self, page: int) -> dict:
        """
        Параметри пошуку в URL. Це «груба» фільтрація на боці Immoweb;
        точну робить aggregator/filters.py уже в нас.
        """
        c = self.criteria
        params: dict[str, object] = {
            "countries": "BE",
            "page": page,
            "orderBy": "newest",
        }
        if c.postal_codes:
            params["postalCodes"] = ",".join(c.postal_codes)
        if c.price_min is not None:
            params["minPrice"] = int(c.price_min)
        if c.price_max is not None:
            params["maxPrice"] = int(c.price_max)
        if c.bedrooms_min is not None:
            params["minBedroomCount"] = int(c.bedrooms_min)
        if c.bedrooms_max is not None:
            params["maxBedroomCount"] = int(c.bedrooms_max)
        return params

    # -- основний метод -------------------------------------------

    def fetch(self) -> Iterator[Listing]:
        url = self._SEARCH_URL.format(
            path=self._path_segment(),
            transaction=self._transaction_segment(),
        )

        for page in range(1, self.http.max_pages + 1):
            log.info("immoweb: сторінка %d", page)
            resp = self.session.get(
                url, params=self._params(page), timeout=self.http.timeout_seconds
            )
            resp.raise_for_status()
            payload = resp.json()

            results = payload.get("results") or []
            if not results:
                log.info("immoweb: більше результатів немає (сторінка %d)", page)
                break

            for item in results:
                listing = self._to_listing(item)
                if listing is not None:
                    yield listing

            total_pages = payload.get("totalPages") or payload.get("pageCount")
            if total_pages and page >= int(total_pages):
                break

            self._sleep()

    # -- перетворення сирого запису в Listing ---------------------

    def _to_listing(self, item: dict) -> Optional[Listing]:
        raw_id = item.get("id")
        if raw_id is None:
            return None

        prop = item.get("property") or {}
        location = prop.get("location") or {}

        price = (
            self._dig(item, "price", "mainValue")
            or self._dig(item, "transaction", "sale", "price")
            or self._dig(item, "transaction", "rental", "monthlyRentalPrice")
        )
        api_type = str(prop.get("type") or "").upper()
        postal = location.get("postalCode")

        return Listing(
            site=self.site_name,
            site_listing_id=str(raw_id),
            url=self._CLASSIFIED_URL.format(id=raw_id),
            title=self._make_title(prop, location),
            price=float(price) if price is not None else None,
            currency="EUR",
            transaction=self.criteria.transaction,
            property_type=_API_TYPE_TO_SIMPLE.get(api_type, api_type.lower() or None),
            bedrooms=prop.get("bedroomCount"),
            living_area=prop.get("netHabitableSurface"),
            locality=location.get("locality"),
            postal_code=str(postal) if postal is not None else None,
            street=location.get("street") or None,
            house_number=str(location["number"]) if location.get("number") is not None else None,
            photo_url=self._dig(item, "media", "pictures", 0, "mediumUrl"),
            raw=item,
        )

    @staticmethod
    def _make_title(prop: dict, location: dict) -> str:
        bits: list[str] = []
        if prop.get("type"):
            bits.append(str(prop["type"]).replace("_", " ").title())
        if prop.get("bedroomCount") is not None:
            bits.append(f'{prop["bedroomCount"]} спалень')
        if location.get("locality"):
            bits.append(str(location["locality"]))
        return " · ".join(bits) or "Оголошення Immoweb"
