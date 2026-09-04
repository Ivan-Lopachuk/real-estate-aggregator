"""
Scraper для Immovlan.be.

ЧОМУ HTML, А НЕ JSON API
------------------------
На відміну від Immoweb, Immovlan не віддає окремий JSON за заголовком
Accept — зате сторінка результатів пошуку сама по собі проста звичайна
HTML-розмітка (сервер її одразу повністю рендерить, без Cloudflare чи
іншого захисту), де кожна картка оголошення — це один `<article
class="v3-search-card">` із семантичними мітками schema.org (`itemprop=
"postalCode"` тощо). Дістаємо потрібні поля бібліотекою BeautifulSoup —
надійніше, ніж руками шукати по тексту, і стійкіше до дрібних змін
верстки, ніж regex по всьому HTML.

Адреса сторінки пошуку має такий вигляд:

    https://immovlan.be/en/real-estate?transactiontypes=for-rent
        &propertytypes=house&towns=9000-gent,8500-kortrijk
        &minprice=600&maxprice=800&page=2

`towns` приймає голі поштові індекси (сайт сам підставляє назву міста
через редирект, напр. "9000" -> "9000-gent") — окремий довідник
населених пунктів, як для Zimmo, тут не потрібен.

Сторінка конкретного оголошення:
    https://immovlan.be/en/detail/<підтип>/<for-rent|for-sale>/<індекс>/<місто>/<код>
"""

from __future__ import annotations

import logging
import re
from typing import Iterator, Optional

from bs4 import BeautifulSoup, Tag

from ..models import Listing
from .base import BaseScraper, register

log = logging.getLogger(__name__)

_BASE_URL = "https://immovlan.be"
_SEARCH_URL = f"{_BASE_URL}/en/real-estate"

_TRANSACTION_TO_SEGMENT = {"rent": "for-rent", "sale": "for-sale"}

_BEDROOMS_RE = re.compile(r"^(\d+)\s*Bedroom")
_AREA_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*m\xb2$")


@register
class ImmovlanScraper(BaseScraper):
    site_name = "immovlan"

    def fetch(self) -> Iterator[Listing]:
        transaction_segment = _TRANSACTION_TO_SEGMENT.get(self.criteria.transaction, "for-rent")

        for property_type in self._property_types():
            yield from self._fetch_search_pages(transaction_segment, property_type)

    # -- побудова запиту --------------------------------------------

    def _property_types(self) -> list[str]:
        """
        Immovlan сам ділить житло на "house" і "apartment" (той самий
        поділ, що й у нас) — тож окремої таблиці відповідності не треба.
        Фільтруємо по одному типу за раз, щоб знати property_type
        кожного результату напевно (сама картка типом не підписана).
        """
        types = [t.lower() for t in self.criteria.property_types if t.lower() in ("house", "apartment")]
        return types or ["house", "apartment"]

    def _params(self, transaction_segment: str, property_type: str, page: int) -> dict:
        c = self.criteria
        params: dict[str, object] = {
            "transactiontypes": transaction_segment,
            "propertytypes": property_type,
            "page": page,
        }
        if c.postal_codes:
            params["towns"] = ",".join(c.postal_codes)
        if c.price_min is not None:
            params["minprice"] = int(c.price_min)
        if c.price_max is not None:
            params["maxprice"] = int(c.price_max)
        return params

    # -- завантаження і розбір сторінки пошуку ------------------------

    def _fetch_search_pages(self, transaction_segment: str, property_type: str) -> Iterator[Listing]:
        for page in range(1, self.http.max_pages + 1):
            log.info("immovlan: %s/%s (сторінка %d)", transaction_segment, property_type, page)
            resp = self.session.get(
                _SEARCH_URL,
                params=self._params(transaction_segment, property_type, page),
                timeout=self.http.timeout_seconds,
            )
            resp.raise_for_status()

            cards = BeautifulSoup(resp.text, "html.parser").select("article.v3-search-card")
            if not cards:
                break

            for card in cards:
                listing = self._to_listing(card, property_type)
                if listing is not None:
                    yield listing

            self._sleep()

    # -- перетворення однієї картки в Listing ---------------------

    def _to_listing(self, card: Tag, property_type: str) -> Optional[Listing]:
        url = card.get("data-url")
        if not url:
            return None
        listing_id = url.rstrip("/").rsplit("/", 1)[-1]

        postal_el = card.select_one('[itemprop="postalCode"]')
        locality_el = card.select_one('[itemprop="addressLocality"]')
        img = card.select_one("img")

        bedrooms = None
        living_area = None
        for pill in card.select(".v3-search-card-pill"):
            text = pill.get_text(" ", strip=True)
            m = _BEDROOMS_RE.match(text)
            if m:
                bedrooms = int(m.group(1))
                continue
            m = _AREA_RE.match(text)
            if m:
                living_area = float(m.group(1).replace(",", "."))

        locality = locality_el.get_text(strip=True) if locality_el else None

        return Listing(
            site=self.site_name,
            site_listing_id=listing_id,
            url=url,
            title=self._make_title(property_type, bedrooms, locality),
            price=self._price(card),
            currency="EUR",
            transaction=self.criteria.transaction,
            property_type=property_type,
            bedrooms=bedrooms,
            living_area=living_area,
            locality=locality,
            postal_code=postal_el.get_text(strip=True) if postal_el else None,
            photo_url=self._photo_url(img),
        )

    @staticmethod
    def _price(card: Tag) -> Optional[float]:
        price_el = card.select_one(".v3-search-card-price")
        if price_el is None:
            return None
        digits = re.sub(r"[^\d]", "", price_el.get_text())
        return float(digits) if digits else None

    @staticmethod
    def _photo_url(img: Optional[Tag]) -> Optional[str]:
        if img is None:
            return None
        return img.get("data-src") or img.get("src") or None

    @staticmethod
    def _make_title(property_type: str, bedrooms: Optional[int], locality: Optional[str]) -> str:
        bits = [property_type.title()]
        if bedrooms is not None:
            bits.append(f"{bedrooms} спалень")
        if locality:
            bits.append(locality)
        return " · ".join(bits) or "Оголошення Immovlan"
