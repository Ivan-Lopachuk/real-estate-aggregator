"""
Перевірка, чи доступний оптоволоконний інтернет (fiber) Proximus за
адресою оголошення.

ЯК ЦЕ ПРАЦЮЄ
------------
На сайті proximus.be є калькулятор «чи є оптика за моєю адресою»
(сторінка fiber-availability-check.html). Він звертається до двох
технічних адрес, які працюють без входу в акаунт — так само, як і на
самому сайті, коли ним просто користуються, не заходячи в кабінет:

1. `/rest/address/autoComplete/text` — знаходить адресу в довіднику
   Proximus за текстом (вулиця, номер, індекс, місто) і повертає її
   внутрішній ідентифікатор `lomKey`.
2. `/.rest/private/personalization/v1/e2e/address` — за цим `lomKey`
   повертає, чи є там оптика (`fiberEligibility`), і деталі технології.

Слово "private" у другій адресі — це просто внутрішня назва застосунку
Proximus, а не ознака того, що потрібен вхід в акаунт: перевірено,
запит працює анонімно.

Це неофіційний, недокументований механізм (Proximus ніде не публікує
його як API для сторонніх програм). Назви полів чи сама адреса можуть
колись змінитися — якщо перевірка почне постійно повертати `None`
(«невідомо»), можливо, щось на боці Proximus змінилося.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger(__name__)

_AUTOCOMPLETE_URL = "https://www.proximus.be/rest/address/autoComplete/text"
_ELIGIBILITY_URL = "https://www.proximus.be/.rest/private/personalization/v1/e2e/address"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class FiberAvailability:
    available: bool
    technology: Optional[str] = None  # напр. "FTTHBF" (оптика); None — якщо немає


def check_fiber(
    street: Optional[str],
    house_number: Optional[str],
    postal_code: Optional[str],
    locality: Optional[str],
    timeout: float = 15.0,
) -> Optional[FiberAvailability]:
    """
    Повертає FiberAvailability або None, якщо адресу не вдалося
    однозначно знайти в довіднику Proximus чи сталася мережева помилка.
    У разі None ми просто НЕ показуємо статус — не вигадуємо відповідь.
    """
    if not street or not house_number or not postal_code:
        return None

    query = f"{street} {house_number}, {postal_code} {locality or ''}".strip()
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    try:
        resp = requests.get(
            _AUTOCOMPLETE_URL,
            params={
                "query": query,
                "entityType": "geographicalAddress",
                "language": "en",
                "type": "main",
            },
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        matches = resp.json().get("adrList") or []
    except Exception:
        log.warning("proximus: не вдалося знайти адресу %r у довіднику", query, exc_info=True)
        return None

    # Довіряємо лише збігу, у якого поштовий індекс точно такий самий,
    # як в оголошення — щоб випадково не взяти вулицю з іншого міста.
    match = next(
        (m for m in matches if str((m.get("main") or {}).get("zipCode")) == str(postal_code)),
        None,
    )
    if match is None:
        log.info("proximus: адресу %r не знайдено в довіднику Proximus", query)
        return None

    lom_key = (match.get("keys") or {}).get("lomKey")
    if lom_key is None:
        return None

    try:
        resp = requests.post(
            _ELIGIBILITY_URL,
            params={"siteName": "iportal"},
            json={"lomKey": lom_key},
            headers={**headers, "Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.warning("proximus: не вдалося перевірити оптику для %r", query, exc_info=True)
        return None

    available = bool(data.get("fiberEligibility"))
    technology = (data.get("serviceQualificationInfoBean") or {}).get("zoningTechnology") or None
    return FiberAvailability(available=available, technology=technology)
