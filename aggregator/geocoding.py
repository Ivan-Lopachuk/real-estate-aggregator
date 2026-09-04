"""
Спільний довідник населених пунктів Бельгії — відкритий, безкоштовний
API geo-api.zimmo.be/places (список усіх міст/районів країни з їхніми
поштовими індексами). Один запит повертає ~3300 записів, тож тут же —
невеликий кеш у пам'яті процесу, щоб не завантажувати довідник заново
на кожен виклик у межах одного запуску.

Використовується у двох місцях:
    * aggregator/scrapers/zimmo.py — перетворює поштовий індекс
      з config.yaml на частину адреси сторінки пошуку (slug на кшталт
      "gent-9000");
    * server/app.py (AI-чат на дошці) — перетворює вільний текст,
      який написала людина ("Антверпен", "Мерксем"), на поштові
      індекси для одноразового пошуку.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

_PLACES_URL = "https://geo-api.zimmo.be/places"

_cache: Optional[list[dict]] = None

# Довідник geo-api.zimmo.be знає назви лише нідерландською/французькою/
# німецькою — українських немає. Тут невеликий власний список
# найпоширеніших бельгійських міст, щоб "Гент" чи "Антверпен" теж
# спрацьовували (у чаті й у формі "Розсилка" — обидва йдуть через
# postal_codes_for_name нижче).
UKRAINIAN_ALIASES: dict[str, str] = {
    "гент": "Gent",
    "антверпен": "Antwerpen",
    "брюссель": "Brussel",
    "льєж": "Liège",
    "ліеж": "Liège",
    "льєз": "Liège",
    "кортрейк": "Kortrijk",
    "брюгге": "Brugge",
    "намюр": "Namur",
    "левен": "Leuven",
    "льовен": "Leuven",
    "мехелен": "Mechelen",
    "остенде": "Oostende",
    "шарлеруа": "Charleroi",
    "монс": "Mons",
    "мерксем": "Merksem",
    "гасселт": "Hasselt",
    "хасселт": "Hasselt",
    "алст": "Aalst",
    "синт-ніклас": "Sint-Niklaas",
    "сінт-ніклас": "Sint-Niklaas",
    "тюрнхаут": "Turnhout",
    "вавр": "Wavre",
    "генк": "Genk",
}


def load_places(
    timeout: float = 20.0, session: Optional[requests.Session] = None
) -> list[dict]:
    """
    Завантажує (і кешує в пам'яті процесу) довідник населених пунктів.
    Повертає [] і пише в журнал, якщо запит не вдався — виклики нижче
    толерантні до порожнього списку (просто нічого не знайдуть).
    """
    global _cache
    if _cache is not None:
        return _cache

    http = session or requests
    try:
        resp = http.get(_PLACES_URL, timeout=timeout)
        resp.raise_for_status()
        _cache = list((resp.json().get("places") or {}).values())
    except Exception:
        log.exception("geocoding: не вдалося завантажити довідник населених пунктів")
        return []
    return _cache


def slugs_for_postal_codes(
    postal_codes: list[str], places: Optional[list[dict]] = None
) -> tuple[list[str], set[str]]:
    """
    Поштові індекси -> список унікальних slug'ів вигляду "gent-9000"
    (частина адреси сторінки пошуку Zimmo). Друге значення — множина
    індексів, для яких щось знайшлось, щоб виклик міг попередити про
    відсутні.
    """
    wanted = set(postal_codes)
    places = load_places() if places is None else places

    slugs: list[str] = []
    found: set[str] = set()
    for place in places:
        # Поштовий індекс лежить не в самому записі, а в
        # адміністративній одиниці, до якої він прив'язаний.
        admin_area = place.get("administrativeArea") or {}
        code = str(admin_area.get("postalCode") or "")
        if code not in wanted:
            continue
        slug = (place.get("slugs") or {}).get("nl") or admin_area.get("slug")
        if not slug:
            continue
        combined = f"{slug}-{code}"
        if combined not in slugs:
            slugs.append(combined)
        found.add(code)
    return slugs, found


def postal_codes_for_name(
    text: str, places: Optional[list[dict]] = None, limit: int = 10
) -> list[str]:
    """
    Вільний текст (напр. "Антверпен", "Merksem") -> список поштових
    індексів населених пунктів, чия назва відповідає цьому тексту
    (регістр не важливий; порівнюємо і з нідерландською назвою, і з
    відомими альтернативними назвами).

    Спершу шукаємо ТОЧНИЙ збіг назви (напр. "gent" == "gent") — якщо
    знайшли хоча б один, повертаємо лише такі. Це важливо: пошук лише
    за підрядком плутав би "Gent" із населеними пунктами, у назві яких
    просто є ці літери десь усередині (напр. "Gentinnes", "Argenteau").
    Якщо точного збігу немає — тоді вже шукаємо за підрядком.
    """
    needle = text.strip().lower()
    if not needle:
        return []
    needle = UKRAINIAN_ALIASES.get(needle, needle).lower()
    places = load_places() if places is None else places

    exact: list[str] = []
    partial: list[tuple[int, str]] = []
    seen_exact: set[str] = set()
    seen_partial: set[str] = set()

    for place in places:
        admin_area = place.get("administrativeArea") or {}
        code = str(admin_area.get("postalCode") or "")
        if not code:
            continue

        names: set[str] = set()
        for value in (place.get("translations") or {}).values():
            if value:
                names.add(str(value).lower())
        for alias in place.get("aliases") or []:
            name = alias.get("name")
            if name:
                names.add(str(name).lower())

        if needle in names and code not in seen_exact:
            exact.append(code)
            seen_exact.add(code)
            continue

        matching = [n for n in names if needle in n]
        if matching and code not in seen_partial:
            partial.append((min(len(n) for n in matching), code))
            seen_partial.add(code)

    if exact:
        return exact[:limit]

    partial.sort(key=lambda pair: pair[0])
    return [code for _, code in partial[:limit]]
