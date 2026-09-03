"""
Генерація даних для веб-дошки оголошень (GitHub Pages).

Після кожного проходу програма перезаписує `<output_dir>/data.json` усіма
оголошеннями з бази за останні ~90 днів. Готова сторінка
`<output_dir>/index.html` (лежить у репозиторії, її генерувати не треба)
читає цей файл у браузері й показує список, запам'ятовуючи в самому
браузері, які оголошення ти вже відкрив.

Сам HTML тут не генерується навмисно: сторінка статична, а змінюються
лише дані.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import WebpageSettings
from .database import Database

log = logging.getLogger(__name__)

_RECENT_DAYS = 90


def _row_to_dict(row) -> dict:
    return {
        "uid": row["uid"],
        "site": row["site"],
        "url": row["url"],
        "title": row["title"],
        "price": row["price"],
        "extra_costs": row["extra_costs"],
        "currency": row["currency"],
        "transaction": row["transaction_kind"],
        "property_type": row["property_type"],
        "bedrooms": row["bedrooms"],
        "living_area": row["living_area"],
        "locality": row["locality"],
        "postal_code": row["postal_code"],
        "street": row["street"],
        "house_number": row["house_number"],
        "photo_url": row["photo_url"],
        "fiber_available": None if row["fiber_available"] is None else bool(row["fiber_available"]),
        "first_seen_utc": row["first_seen_utc"],
    }


def _build_listings(rows) -> list[dict]:
    """
    Перетворює рядки бази на список для дошки. Дублікати (оголошення з
    заповненим `duplicate_of` — те саме, що вже є з іншого сайту) не
    стають окремими картками: замість цього їхнє посилання додається до
    оригіналу в поле `also_on`, щоб на дошці була одна картка, а не дві
    однакові.
    """
    listings = [_row_to_dict(r) for r in rows if not r["duplicate_of"]]
    by_uid = {l["uid"]: l for l in listings}

    for row in rows:
        original_uid = row["duplicate_of"]
        if not original_uid or original_uid not in by_uid:
            continue
        by_uid[original_uid].setdefault("also_on", []).append(
            {"site": row["site"], "url": row["url"]}
        )

    return listings


def write_data(db: Database, settings: WebpageSettings, search_summary: str) -> None:
    """Перезаписати <output_dir>/data.json поточним станом бази."""
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = db.recent_listings(days=_RECENT_DAYS)
    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "search_summary": search_summary,
        "recent_days": _RECENT_DAYS,
        "listings": _build_listings(rows),
    }

    data_file = out_dir / "data.json"
    data_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    log.info(
        "веб-дошка: оновлено %s (%d карток, %d записів у базі)",
        data_file, len(payload["listings"]), len(rows),
    )
