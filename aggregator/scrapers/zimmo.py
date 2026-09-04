"""
Scraper для Zimmo.be — другого підключеного сайту.

ЧОМУ ТУТ ІНАКШЕ, НІЖ У IMMOWEB
-------------------------------
У Immoweb є окремий JSON API: можна попросити дані, не отримуючи HTML
взагалі (див. коментар у immoweb.py). У Zimmo такого прямого способу
немає — але сторінка результатів пошуку (та сама, яку бачить людина в
браузері) вбудовує повний список оголошень як готовий JSON просто
всередині HTML, у місці виклику `app.start({ ... properties: [...] })`.
Ми відкриваємо звичайну сторінку пошуку і дістаємо звідти саме цей
шматок. Дані там такі самі структуровані й надійні, як у справжньому
API (ціна, спальні, площа, адреса — усе окремими полями, а не текстом
для читання людиною) — просто дістати їх треба трохи інакше, ніж у
Immoweb.

Адреса сторінки пошуку має такий вигляд:

    https://www.zimmo.be/nl/gent-9000/te-huur/appartement/?p=2
                              │           │        │         │
                       населений пункт  оренда  тип житла  сторінка

"gent-9000" — це частина адреси (slug) для конкретного поштового
індексу. Список усіх slug'ів Бельгії з їхніми поштовими індексами ми
один раз завантажуємо з відкритого довідника geo-api.zimmo.be/places і
шукаємо в ньому потрібні індекси з config.yaml.

Якщо в config.yaml -> search -> postal_codes нічого не вказано —
шукаємо по всій Бельгії через адресу /nl/zoek/te-huur/appartement/
(без назви населеного пункту).

Сторінка завжди повертає щонайбільше 21 оголошення. Якщо їх менше —
це остання сторінка.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterator, Optional

from curl_cffi import requests as cffi_requests

from .. import geocoding
from ..config import HttpSettings, SearchCriteria
from ..models import Listing
from .base import BaseScraper, register

log = logging.getLogger(__name__)

_BASE_URL = "https://www.zimmo.be"
_PAGE_SIZE = 21

_TRANSACTION_TO_SEGMENT = {"rent": "te-huur", "sale": "te-koop"}
_TYPE_TO_SEGMENT = {"house": "huis", "apartment": "appartement"}
_SEGMENT_TO_TYPE = {v: k for k, v in _TYPE_TO_SEGMENT.items()}


@register
class ZimmoScraper(BaseScraper):
    site_name = "zimmo"

    def __init__(self, criteria: SearchCriteria, http: HttpSettings) -> None:
        super().__init__(criteria, http)
        # Сторінка пошуку Zimmo (на відміну від Immoweb) стоїть за
        # Cloudflare-захистом. Проста бібліотека requests (і навіть
        # cloudscraper, яка лише розв'язує JS-загадку) віддає 403 —
        # причина глибша: Cloudflare розпізнає непрозорий "відбиток"
        # TLS-з'єднання (JA3), яким Python-requests відрізняється від
        # справжнього Chrome. curl_cffi відтворює TLS-з'єднання Chrome
        # один-в-один (через libcurl/BoringSSL, а не системний OpenSSL),
        # тож відбиток той самий незалежно від ОС — де запускати.
        self.session = cffi_requests.Session(impersonate="chrome124")

    def fetch(self) -> Iterator[Listing]:
        status_segment = _TRANSACTION_TO_SEGMENT.get(self.criteria.transaction, "te-huur")
        type_segments = self._type_segments()
        locality_prefixes = self._locality_prefixes()

        for prefix in locality_prefixes:
            for type_segment in type_segments:
                base_url = f"{_BASE_URL}{prefix}/{status_segment}/{type_segment}/"
                yield from self._fetch_search_pages(base_url, type_segment)

    # -- побудова адрес пошуку ---------------------------------------

    def _type_segments(self) -> list[str]:
        """Які частини адреси (huis/appartement) опитувати."""
        segments: list[str] = []
        for t in self.criteria.property_types:
            seg = _TYPE_TO_SEGMENT.get(t)
            if seg and seg not in segments:
                segments.append(seg)
        return segments or list(_TYPE_TO_SEGMENT.values())

    def _locality_prefixes(self) -> list[str]:
        """
        Список частин адреси з населеним пунктом, напр. ["/nl/gent-9000"].
        Якщо поштові індекси не задані — повертає ["/nl/zoek"] (уся
        Бельгія). Сам пошук slug'а за поштовим індексом — у
        aggregator/geocoding.py (спільний з AI-чатом довідник).
        """
        if not self.criteria.postal_codes:
            return ["/nl/zoek"]

        places = geocoding.load_places(timeout=self.http.timeout_seconds, session=self.session)
        slugs, found = geocoding.slugs_for_postal_codes(self.criteria.postal_codes, places)

        missing = set(self.criteria.postal_codes) - found
        if missing:
            log.warning(
                "zimmo: не знайдено населений пункт для поштових індексів: %s",
                ", ".join(sorted(missing)),
            )
        return [f"/nl/{slug}" for slug in slugs]

    # -- завантаження і розбір сторінки пошуку ------------------------

    def _fetch_search_pages(self, base_url: str, type_segment: str) -> Iterator[Listing]:
        for page in range(1, self.http.max_pages + 1):
            url = base_url if page == 1 else f"{base_url}?p={page}"
            log.info("zimmo: %s (сторінка %d)", base_url, page)
            resp = self.session.get(url, timeout=self.http.timeout_seconds)
            if resp.status_code == 404:
                log.info("zimmo: адреси %s не існує — пропускаємо", base_url)
                break
            resp.raise_for_status()

            items = self._extract_properties(resp.text)
            if not items:
                break

            for item in items:
                listing = self._to_listing(item, type_segment)
                if listing is not None:
                    yield listing

            if len(items) < _PAGE_SIZE:
                break
            self._sleep()

    @staticmethod
    def _extract_properties(html: str) -> list[dict]:
        """
        Дістає масив `properties: [...]` із вбудованого в HTML виклику
        `app.start({...})`. Повертає [], якщо на сторінці його немає
        (напр. це сторінка помилки) або він пошкоджений.
        """
        marker = "properties: ["
        start_marker = html.find(marker)
        if start_marker == -1:
            return []

        start = start_marker + len("properties: ")
        depth = 0
        end = None
        for i in range(start, len(html)):
            ch = html[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            return []

        try:
            return json.loads(html[start:end])
        except json.JSONDecodeError:
            log.warning("zimmo: не вдалося розібрати список оголошень на сторінці")
            return []

    # -- перетворення сирого запису в Listing ---------------------

    def _to_listing(self, item: dict, type_segment: str) -> Optional[Listing]:
        code = item.get("code")
        if not code:
            return None

        url = item.get("url") or item.get("pand_url") or ""
        if url and not url.startswith("http"):
            url = _BASE_URL + url

        postal_code = item.get("postcode")
        street, house_number = self._split_address(item.get("address"))

        return Listing(
            site=self.site_name,
            site_listing_id=str(code),
            url=url,
            title=self._make_title(item),
            price=self._to_float(item.get("prijs")),
            currency="EUR",
            transaction=self.criteria.transaction,
            property_type=_SEGMENT_TO_TYPE.get(type_segment, type_segment),
            bedrooms=self._to_int(item.get("slaapkamers")),
            living_area=self._to_float(item.get("b_woonopp")),
            locality=item.get("gemeente") or None,
            postal_code=str(postal_code) if postal_code else None,
            street=street,
            house_number=house_number,
            photo_url=item.get("hoofdFoto") or None,
            listed_at=self._to_iso_timestamp(item.get("toegevoegd")),
            raw=item,
        )

    @staticmethod
    def _to_iso_timestamp(unix_seconds) -> Optional[str]:
        """Zimmo дає час додавання оголошення як unix-час (текстом)."""
        if not unix_seconds:
            return None
        try:
            return datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc).isoformat(
                timespec="seconds"
            )
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _split_address(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """
        Zimmo дає адресу одним рядком, напр. "Sint-Lievenspoortstraat 77".
        Ділимо на назву вулиці й номер будинку (номер — останнє слово, що
        починається з цифри).
        """
        if not address:
            return None, None
        parts = address.rsplit(" ", 1)
        if len(parts) == 2 and parts[1][:1].isdigit():
            return parts[0].strip() or None, parts[1].strip()
        return address.strip() or None, None

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _to_int(cls, value) -> Optional[int]:
        as_float = cls._to_float(value)
        return int(as_float) if as_float is not None else None

    @staticmethod
    def _make_title(item: dict) -> str:
        bits: list[str] = []
        if item.get("type"):
            bits.append(str(item["type"]))
        beds = item.get("slaapkamers")
        if beds not in (None, ""):
            bits.append(f"{beds} спалень")
        if item.get("gemeente"):
            bits.append(str(item["gemeente"]))
        return " · ".join(bits) or "Оголошення Zimmo"
