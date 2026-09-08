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

ТОЧНА АДРЕСА — З ОКРЕМОЇ СТОРІНКИ ОГОЛОШЕННЯ
-------------------------------------------
Картка в результатах пошуку показує лише місто й поштовий індекс. Саму
вулицю й номер будинку Immovlan пише вже на сторінці конкретного
оголошення — у блоці schema.org JSON-LD (`"@type": "RealEstateListing"`,
поле `mainEntity.address.streetAddress`). Тож для кожного оголошення
робимо ще один запит — на його сторінку — і дістаємо адресу звідти.
Її використовує і кнопка «📍 На карті» на дошці, і перевірка оптики
Proximus (aggregator/proximus.py). Щоб один запуск не зробив тисячу
запитів на великій вибірці, кількість таких додаткових звернень
обмежена (`_MAX_DETAIL_LOOKUPS`) — решта оголошень просто лишаться без
точної адреси (на карті покажеться місто).

Оголошенням, які потрапили в базу ще без адреси (стара версія програми
або тимчасовий збій запиту), її потім дозаповнює runner —
`_backfill_immovlan_addresses()` через метод `addresses_for_urls()`
нижче, доки сторінка оголошення ще жива.

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

import dataclasses
import json
import logging
import re
from typing import Iterable, Iterator, Optional

from bs4 import BeautifulSoup, Tag

from ..models import Listing
from .base import BaseScraper, register

log = logging.getLogger(__name__)

_BASE_URL = "https://immovlan.be"
_SEARCH_URL = f"{_BASE_URL}/en/real-estate"

_TRANSACTION_TO_SEGMENT = {"rent": "for-rent", "sale": "for-sale"}

_BEDROOMS_RE = re.compile(r"^(\d+)\s*Bedroom")
_AREA_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*m\xb2$")

# Розбір рядка адреси Immovlan на (вулиця, номер будинку). Формат буває:
#   "Kerkstraat 12"                     -> ("Kerkstraat", "12")
#   "Sint-Denijssestraat 171"           -> ("Sint-Denijssestraat", "171")
#   "Avenue des Villas 12A"             -> ("Avenue des Villas", "12A")
#   "Paleisstraat 3 0031"  (3 = дім, 0031 = бокс/поштова скринька)
#                                       -> ("Paleisstraat", "3")
#   "Raveschootstraat 2/201"            -> ("Raveschootstraat", "2")
# Беремо ПЕРШЕ число як номер будинку; усе після нього (бокс, "bus 3",
# "/201") відкидаємо — для карти й перевірки оптики потрібен саме дім.
_STREET_NUMBER_RE = re.compile(r"^(.*?)\s+(\d+[a-zA-Z]?)(?:[\s/].*)?$")

# Скільки сторінок окремих оголошень максимум відкриваємо за один
# запуск заради точної адреси. Захист від тисяч запитів, якщо вибірка
# раптом стане дуже великою — на звичайному пошуку по кількох містах
# оголошень набагато менше.
_MAX_DETAIL_LOOKUPS = 100


@register
class ImmovlanScraper(BaseScraper):
    site_name = "immovlan"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Скільки сторінок окремих оголошень уже відкрито за цей об'єкт
        # (обмежуємо на _MAX_DETAIL_LOOKUPS — див. константу вгорі).
        self._detail_lookups = 0

    def fetch(self) -> Iterator[Listing]:
        transaction_segment = _TRANSACTION_TO_SEGMENT.get(self.criteria.transaction, "for-rent")
        self._detail_lookups = 0

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
                    yield self._with_exact_address(listing)

            self._sleep()

    # -- точна адреса зі сторінки оголошення ------------------------

    def _with_exact_address(self, listing: Listing) -> Listing:
        """
        Доповнює `listing` вулицею й номером будинку зі сторінки самого
        оголошення. Якщо ліміт запитів вичерпано або адресу дістати не
        вдалося — повертає оголошення без змін (на карті буде місто).
        """
        street, house_number = self._address_from_url(listing.url)
        if not street:
            return listing
        return dataclasses.replace(listing, street=street, house_number=house_number)

    def addresses_for_urls(
        self, urls: Iterable[str]
    ) -> dict[str, tuple[str, Optional[str]]]:
        """
        Для набору сторінок оголошень повертає {url: (вулиця, номер)} —
        лише для тих, де адресу вдалося дістати. Спільний ліміт запитів
        (`_MAX_DETAIL_LOOKUPS`) той самий, що й у звичайному проході.
        Використовує runner, щоб дозаповнити адресу оголошенням, які вже
        давно в базі без неї.
        """
        found: dict[str, tuple[str, Optional[str]]] = {}
        for url in urls:
            street, house_number = self._address_from_url(url)
            if street:
                found[url] = (street, house_number)
        return found

    def _address_from_url(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Один запит на сторінку оголошення (з урахуванням ліміту й паузи)."""
        if self._detail_lookups >= _MAX_DETAIL_LOOKUPS:
            if self._detail_lookups == _MAX_DETAIL_LOOKUPS:
                log.warning(
                    "immovlan: досягнуто ліміту %d запитів по точну адресу — "
                    "решта оголошень лишаться без вулиці",
                    _MAX_DETAIL_LOOKUPS,
                )
                self._detail_lookups += 1  # щоб попередити лише раз
            return None, None

        self._detail_lookups += 1
        street, house_number = self._fetch_detail_address(url)
        self._sleep()
        return street, house_number

    def _fetch_detail_address(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Завантажує сторінку оголошення й дістає з неї адресу."""
        try:
            resp = self.session.get(url, timeout=self.http.timeout_seconds)
            resp.raise_for_status()
        except Exception:
            log.warning("immovlan: не вдалося відкрити сторінку оголошення %s", url, exc_info=True)
            return None, None
        return self._parse_detail_address(resp.text)

    @staticmethod
    def _parse_detail_address(html: str) -> tuple[Optional[str], Optional[str]]:
        """
        Дістає адресу з блоків schema.org JSON-LD на сторінці оголошення.
        Беремо саме `mainEntity.address` (сама нерухомість) — НЕ
        `offers.offeredBy.address`, бо то адреса агентства. Якщо
        оголошення вже зняте, Immovlan віддає замість нього список інших
        квартир — там `mainEntity` без адреси, і ми повертаємо (None, None).
        """
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(tag.string or "")
            except (ValueError, TypeError):
                continue
            street_address = ImmovlanScraper._street_address_from_jsonld(data)
            if street_address:
                return _split_street_and_number(street_address)
        return None, None

    @staticmethod
    def _street_address_from_jsonld(data) -> Optional[str]:
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            node = entry.get("mainEntity")
            if not isinstance(node, dict):
                node = entry
            address = node.get("address")
            if isinstance(address, dict):
                street_address = address.get("streetAddress")
                if isinstance(street_address, str) and street_address.strip():
                    return street_address.strip()
        return None

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
        # 0 або відсутнє (студія / сайт не вказав) — не пишемо "0 спалень".
        if bedrooms:
            bits.append(f"{bedrooms} спалень")
        if locality:
            bits.append(locality)
        return " · ".join(bits) or "Оголошення Immovlan"


def _split_street_and_number(street_address: str) -> tuple[str, Optional[str]]:
    """
    Ділить рядок адреси на (вулиця, номер будинку) — так само, як
    Immoweb віддає їх уже окремо, щоб дедуплікація за адресою й перевірка
    оптики Proximus працювали для обох сайтів однаково. Приклади — див.
    коментар біля `_STREET_NUMBER_RE`.
    """
    text = street_address.strip()
    m = _STREET_NUMBER_RE.match(text)
    if m:
        return m.group(1).strip(), m.group(2)
    return text, None
