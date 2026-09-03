#!/usr/bin/env python3
"""
Маленький сервер для AI-чату на дошці (docs/index.html).

Навіщо він потрібен, якщо решта проєкту — статичні файли на GitHub
Pages: щоб чат міг ПРЯМО ЗАРАЗ (за кілька секунд) запустити пошук по
Immoweb і Zimmo та повернути відповідь. Статична сторінка нічого не
запускає сама — потрібен код, що постійно (чи хоча б за запитом)
працює десь окремо. Це і є той код.

Один ендпоїнт: `POST /api/chat`.
    1. Приймає повідомлення людини українською/будь-якою мовою.
    2. Просить AI (через OpenRouter) розібрати його на критерії пошуку
       (місто, ціна, спальні, площа тощо) — модель повертає суворий JSON.
    3. Назву міста/району перетворює на поштові індекси через
       aggregator/geocoding.py (спільний з Zimmo-scraper довідник).
    4. Запускає ті самі scraper'и, що й основна програма
       (aggregator/scrapers/), і той самий фільтр (aggregator/filters.py) —
       жодного дубльованого коду.
    5. Повертає знайдені оголошення й коротку відповідь AI.

Захист: заголовок `X-Access-Code` має збігатися зі змінною середовища
ACCESS_CODE. Без цього — 401. OPENROUTER_API_KEY ніколи не потрапляє
в браузер — усі виклики OpenRouter відбуваються тут, на сервері.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# aggregator/ лежить на рівень вище цього файлу (той самий репозиторій,
# той самий код, що ганяє GitHub Actions) — додаємо корінь проєкту в
# шлях пошуку модулів, щоб його можна було імпортувати.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregator import geocoding  # noqa: E402
from aggregator.config import HttpSettings, SearchCriteria  # noqa: E402
from aggregator.filters import ListingFilter  # noqa: E402
from aggregator.models import Listing  # noqa: E402
import aggregator.scrapers  # noqa: E402,F401  (імпорт реєструє immoweb/zimmo)
from aggregator.scrapers.base import available_scrapers, get_scraper  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("chat-server")

ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Скільки сторінок кожного сайту опитувати за один запит у чаті —
# менше, ніж у основного розкладу (там 10), щоб відповідь прийшла за
# розумний час, а не за хвилину.
_CHAT_MAX_PAGES = 3
_CHAT_REQUEST_TIMEOUT = 15
_CHAT_REQUEST_DELAY = 0.5

app = Flask(__name__)
CORS(app)

_SYSTEM_PROMPT = """\
Ти розбираєш повідомлення людини, яка шукає нерухомість у Бельгії, на
структуровані критерії пошуку. Відповідай ЛИШЕ одним JSON-об'єктом,
без жодного тексту навколо, з полями:

{
  "reply": "коротка дружня відповідь українською — що саме шукаємо",
  "place": "назва міста/району, яку згадала людина, мовою оригіналу (напр. 'Antwerpen', 'Merksem'); null, якщо не назвала",
  "transaction": "rent" або "sale"; null, якщо не зрозуміло (тоді вважай rent)
  "property_types": підмножина ["house", "apartment"] або null (тоді обидва)
  "price_min": число (євро) або null
  "price_max": число (євро) або null
  "bedrooms_min": ціле число або null
  "bedrooms_max": ціле число або null
  "living_area_min": число (м²) або null
  "days_back": ціле число днів, якщо людина просила показати лише свіжі оголошення (напр. "за останні 2 дні" -> 2); інакше null
}

Якщо людина не назвала місто — постав place: null і у reply попроси
уточнити, у якому місті шукати. Не вигадуй значень, яких немає в
повідомленні — став null.
"""


def _access_ok() -> bool:
    return bool(ACCESS_CODE) and request.headers.get("X-Access-Code") == ACCESS_CODE


def _ask_openrouter(message: str, history: list[dict]) -> Optional[dict]:
    """Питає OpenRouter, повертає розібраний JSON або None, якщо не вдалося."""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for turn in history[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": str(content)})
    messages.append({"role": "user", "content": message})

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        log.exception("не вдалося отримати відповідь від OpenRouter")
        return None

    return _extract_json(content)


def _extract_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _build_criteria(parsed: dict, postal_codes: list[str]) -> SearchCriteria:
    property_types = parsed.get("property_types") or ["house", "apartment"]
    return SearchCriteria(
        transaction="sale" if parsed.get("transaction") == "sale" else "rent",
        property_types=[str(t).lower() for t in property_types],
        price_min=parsed.get("price_min"),
        price_max=parsed.get("price_max"),
        bedrooms_min=parsed.get("bedrooms_min"),
        bedrooms_max=parsed.get("bedrooms_max"),
        living_area_min=parsed.get("living_area_min"),
        postal_codes=postal_codes,
    )


def _search_live(criteria: SearchCriteria) -> list[Listing]:
    http_settings = HttpSettings(
        max_pages=_CHAT_MAX_PAGES,
        request_delay_seconds=_CHAT_REQUEST_DELAY,
        timeout_seconds=_CHAT_REQUEST_TIMEOUT,
    )
    listing_filter = ListingFilter(criteria)
    matched: list[Listing] = []
    for site in available_scrapers():
        scraper = get_scraper(site)(criteria, http_settings)
        try:
            fetched = list(scraper.fetch())
        except Exception:
            log.exception("чат: scraper %r впав", site)
            continue
        matched.extend(listing_filter.apply(fetched))
    return matched


def _parse_listed_at(value: str) -> Optional[datetime]:
    """
    Immoweb і Zimmo дають дату в трохи різних форматах (мілісекунди й
    "Z" проти "+00:00") — порівнювати їх як рядки ненадійно, тож завжди
    розбираємо у справжній datetime.
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _apply_recency(listings: list[Listing], days_back) -> list[Listing]:
    if not days_back:
        return listings
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_back))
    except (TypeError, ValueError):
        return listings

    kept = []
    for l in listings:
        listed_dt = _parse_listed_at(l.listed_at) if l.listed_at else None
        # Якщо дати немає або її не вдалося розібрати — не відкидаємо
        # (бракує даних, а не «старе»), той самий принцип, що й у
        # aggregator/filters.py.
        if listed_dt is None or listed_dt >= cutoff:
            kept.append(l)
    return kept


def _listing_to_dict(l: Listing) -> dict:
    return {
        "uid": l.uid,
        "site": l.site,
        "url": l.url,
        "title": l.title,
        "price": l.price,
        "extra_costs": l.extra_costs,
        "currency": l.currency,
        "bedrooms": l.bedrooms,
        "living_area": l.living_area,
        "locality": l.locality,
        "postal_code": l.postal_code,
        "street": l.street,
        "house_number": l.house_number,
        "photo_url": l.photo_url,
        # Дошка вже вміє малювати "побачено N дн. тому" з цього поля.
        "first_seen_utc": l.listed_at,
    }


@app.route("/api/chat", methods=["POST"])
def chat():
    if not _access_ok():
        return jsonify({"error": "потрібен правильний код доступу"}), 401

    body = request.get_json(force=True, silent=True) or {}
    message = str(body.get("message") or "").strip()
    history = body.get("history") or []
    if not message:
        return jsonify({"error": "порожнє повідомлення"}), 400

    parsed = _ask_openrouter(message, history)
    if parsed is None:
        return jsonify({
            "reply": "Не вдалося розібрати запит (AI не відповів). Спробуй ще раз.",
            "listings": [],
        })

    place = parsed.get("place")
    postal_codes: list[str] = []
    if place:
        postal_codes = geocoding.postal_codes_for_name(str(place))
        if not postal_codes:
            return jsonify({
                "reply": f"Не знайшов населеного пункту «{place}» у Бельгії. "
                         "Спробуй написати назву інакше.",
                "listings": [],
            })

    criteria = _build_criteria(parsed, postal_codes)
    listings = _search_live(criteria)
    listings = _apply_recency(listings, parsed.get("days_back"))

    reply = parsed.get("reply") or f"Знайшов {len(listings)} оголошень."
    return jsonify({
        "reply": reply,
        "listings": [_listing_to_dict(l) for l in listings],
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
