"""
Стрічка сповіщень у кабінеті користувача.

Ті самі нові квартири, що йдуть людині на пошту з її розсилки
(`aggregator/runner.py` -> `run_profiles`), додатково складаються сюди —
щоб їх можна було переглядати прямо на сайті (розділ «Кабінет»), а не
лише в пошті.

Зберігається одним файлом на людину:

    feed/<google_sub>.json      # той самий <google_sub>, що й profiles/<google_sub>.json

Формат:

    {
      "items": [
        {
          "uid": "immoweb:123",
          "title": "...", "url": "...",
          "price": 750, "currency": "EUR",
          "locality": "Gent", "postal_code": "9000",
          "photo_url": "https://...",
          "sent_utc": "2026-09-09T10:00:00+00:00",
          "read": false
        },
        ...
      ]
    }

Найновіші — першими. Список обрізається до `DEFAULT_CAP` записів.

Тут — лише логіка (робота зі словниками) плюс просте читання/запис
файлу, за зразком `aggregator/profiles.py`. Мережею й GitHub API
займається сервер окремо (він теж уміє читати ці файли — для
`GET /api/feed`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from .models import Listing

log = logging.getLogger(__name__)

# Скільки оголошень тримати в стрічці. Старіші за це — випадають
# (їх усе одно видно на самій дошці за посиланням з листа).
DEFAULT_CAP = 200


def listing_to_item(listing: Listing, sent_utc: str) -> dict:
    """Перетворює оголошення на запис стрічки. `read` завжди False (щойно прийшло)."""
    return {
        "uid": listing.uid,
        "title": listing.title,
        "url": listing.url,
        "price": listing.price,
        "currency": listing.currency,
        "bedrooms": listing.bedrooms,
        "living_area": listing.living_area,
        "locality": listing.locality,
        "postal_code": listing.postal_code,
        "street": listing.street,
        "house_number": listing.house_number,
        "photo_url": listing.photo_url,
        "sent_utc": sent_utc,
        "read": False,
    }


def append_items(
    feed: Optional[dict],
    listings: Sequence[Listing],
    sent_utc: str,
    cap: int = DEFAULT_CAP,
) -> dict:
    """
    Додає нові оголошення на початок стрічки. Якщо оголошення вже є в
    стрічці (за `uid`) — воно не дублюється, лишається як було. Повертає
    НОВИЙ словник (старий не змінює).
    """
    existing = list((feed or {}).get("items") or [])
    seen_uids = {item.get("uid") for item in existing}

    fresh = [
        listing_to_item(l, sent_utc)
        for l in listings
        if l.uid not in seen_uids
    ]
    items = fresh + existing
    if cap and len(items) > cap:
        items = items[:cap]
    return {"items": items}


def mark_read(feed: Optional[dict], uids: Optional[Sequence[str]] = None) -> dict:
    """
    Позначає записи прочитаними. `uids=None` -> усі. Повертає новий словник.
    """
    target = set(uids) if uids is not None else None
    items = []
    for item in (feed or {}).get("items") or []:
        copy = dict(item)
        if target is None or copy.get("uid") in target:
            copy["read"] = True
        items.append(copy)
    return {"items": items}


def unread_count(feed: Optional[dict]) -> int:
    """Скільки записів у стрічці ще не прочитано."""
    return sum(
        1 for item in (feed or {}).get("items") or [] if not item.get("read")
    )


# --- читання/запис файлу (для aggregator/runner.py) -----------------

def _feed_path(directory: "str | Path", google_sub: str) -> Path:
    return Path(directory) / f"{google_sub}.json"


def load_feed(directory: "str | Path", google_sub: str) -> dict:
    """Читає feed/<google_sub>.json. Немає файлу або він битий -> порожня стрічка."""
    path = _feed_path(directory, google_sub)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    except Exception:  # noqa: BLE001 — не даємо стрічці зламати розсилку
        log.warning("стрічка %s пошкоджена — починаю з порожньої", path, exc_info=True)
    return {"items": []}


def save_feed(directory: "str | Path", google_sub: str, feed: dict) -> None:
    """Записує стрічку назад у feed/<google_sub>.json (створює теку за потреби)."""
    dir_path = Path(directory)
    dir_path.mkdir(parents=True, exist_ok=True)
    _feed_path(dir_path, google_sub).write_text(
        json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
