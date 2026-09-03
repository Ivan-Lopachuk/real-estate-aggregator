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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

# aggregator/ лежить на рівень вище цього файлу (той самий репозиторій,
# той самий код, що ганяє GitHub Actions) — додаємо корінь проєкту в
# шлях пошуку модулів, щоб його можна було імпортувати.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregator import geocoding, proximus  # noqa: E402
from aggregator.config import HttpSettings, SearchCriteria  # noqa: E402
from aggregator.filters import ListingFilter  # noqa: E402
from aggregator.github_store import GitHubStoreError, read_json, write_json, delete_json  # noqa: E402
from aggregator.models import Listing  # noqa: E402
import aggregator.scrapers  # noqa: E402,F401  (імпорт реєструє immoweb/zimmo)
from aggregator.scrapers.base import available_scrapers, get_scraper  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("chat-server")

ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Client ID застосунку в Google Cloud Console ("Увійти через Google" на
# дошці) — потрібен, щоб перевірити, що токен видано саме для нашого
# сайту, а не підроблений/для чужого застосунку.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

# Щоб сервер міг зберігати профілі розсилки (profiles/<id>.json) прямо
# в репозиторії — сам сервер нічого не пам'ятає між перезапусками.
# GH_WRITE_TOKEN — fine-grained токен із правом Contents: Read and
# write лише на цей репозиторій. GH_REPO — "власник/репозиторій",
# напр. "nastya/real-estate-aggregator".
GH_WRITE_TOKEN = os.environ.get("GH_WRITE_TOKEN", "")
GH_REPO = os.environ.get("GH_REPO", "")

_MIN_INTERVAL_HOURS = 1
_MAX_INTERVAL_HOURS = 168  # тиждень

# Скільки сторінок кожного сайту опитувати за один запит у чаті —
# менше, ніж у основного розкладу (там 10), щоб відповідь прийшла за
# розумний час, а не за хвилину.
_CHAT_MAX_PAGES = 3
_CHAT_REQUEST_TIMEOUT = 15
_CHAT_REQUEST_DELAY = 0.5

# Скільки різних адрес перевіряти на оптику Proximus ОДНОЧАСНО (у
# кілька потоків) — без цього перевірка 50 адрес по черзі (по 2
# мережеві виклики на кожну) займала б надто довго.
_CHAT_FIBER_WORKERS = 8

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


def _build_criteria(parsed: dict, postal_codes: list[str], place: Optional[str] = None) -> SearchCriteria:
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
        localities=[str(place)] if place else [],
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


def _fiber_status_for(listings: list[Listing]) -> dict[str, tuple[bool, Optional[str]]]:
    """
    Перевіряє оптику Proximus для УСІХ оголошень із відомою адресою
    (навіть якщо їх 50) — щоб чат не чекав хвилинами, різні адреси
    перевіряються одночасно в кілька потоків. Кілька квартир в одному
    будинку перевіряються лише раз (кеш за адресою, не за uid).
    """
    # адреса -> список uid оголошень з цією адресою
    addresses: dict[tuple, list[str]] = {}
    address_listing: dict[tuple, Listing] = {}
    for l in listings:
        if not (l.street and l.house_number and l.postal_code):
            continue
        key = (l.street.strip().lower(), l.house_number.strip().lower(), l.postal_code.strip())
        addresses.setdefault(key, []).append(l.uid)
        address_listing.setdefault(key, l)

    if not addresses:
        return {}

    def _check(key: tuple) -> tuple[tuple, Optional[tuple[bool, Optional[str]]]]:
        l = address_listing[key]
        result = proximus.check_fiber(l.street, l.house_number, l.postal_code, l.locality)
        return key, (None if result is None else (result.available, result.technology))

    by_uid: dict[str, tuple[bool, Optional[str]]] = {}
    with ThreadPoolExecutor(max_workers=_CHAT_FIBER_WORKERS) as pool:
        for key, value in pool.map(_check, addresses.keys()):
            if value is None:
                continue
            for uid in addresses[key]:
                by_uid[uid] = value

    return by_uid


def _listing_to_dict(l: Listing, fiber: Optional[tuple[bool, Optional[str]]] = None) -> dict:
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
        "fiber_available": fiber[0] if fiber is not None else None,
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

    criteria = _build_criteria(parsed, postal_codes, place)
    listings = _search_live(criteria)
    listings = _apply_recency(listings, parsed.get("days_back"))
    fiber_map = _fiber_status_for(listings)

    criteria_summary = criteria.summary
    days_back = parsed.get("days_back")
    if days_back:
        criteria_summary += f" · за останні {days_back} дн."

    reply = parsed.get("reply") or f"Знайшов {len(listings)} оголошень."
    return jsonify({
        "reply": reply,
        "criteria_summary": criteria_summary,
        "listings": [_listing_to_dict(l, fiber_map.get(l.uid)) for l in listings],
    })


def _verify_google_token(token: str) -> Optional[dict]:
    """
    Перевіряє токен від кнопки "Увійти через Google" (JWT, підписаний
    Google). Повертає {sub, email, name, picture} лише якщо підпис
    справжній, токен виданий саме для GOOGLE_CLIENT_ID і Google
    підтверджує, що email підтверджений — інакше None.
    """
    if not token or not GOOGLE_CLIENT_ID:
        return None
    try:
        payload = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except Exception:
        log.info("google-вхід: недійсний токен", exc_info=True)
        return None

    if not payload.get("email_verified"):
        return None

    return {
        "sub": payload.get("sub"),
        "email": payload.get("email"),
        "name": payload.get("name") or payload.get("email"),
        "picture": payload.get("picture"),
    }


@app.route("/api/auth/google", methods=["POST"])
def auth_google():
    body = request.get_json(force=True, silent=True) or {}
    token = str(body.get("id_token") or "")
    user = _verify_google_token(token)
    if user is None:
        return jsonify({"error": "Не вдалося підтвердити вхід через Google."}), 401
    return jsonify(user)


def _authenticated_user() -> Optional[dict]:
    """Читає `Authorization: Bearer <google-id-token>` і перевіряє його."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return _verify_google_token(auth[len("Bearer "):].strip())


def _profile_path(google_sub: str) -> str:
    return f"profiles/{google_sub}.json"


def _opt_num(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _validate_subscription_body(body: dict) -> tuple[Optional[dict], Optional[str]]:
    """
    Перевіряє форму розсилки. Повертає (готовий профіль без службових
    полів, None) якщо все гаразд, або (None, повідомлення про помилку).
    """
    place = str(body.get("place") or "").strip()
    if not place:
        return None, "Вкажи місто чи район."

    postal_codes = geocoding.postal_codes_for_name(place)
    if not postal_codes:
        return None, f"Не знайшов населеного пункту «{place}» у Бельгії."

    notify_email = str(body.get("notify_email") or "").strip()
    if "@" not in notify_email or "." not in notify_email.split("@")[-1]:
        return None, "Вкажи коректну електронну пошту для листів."

    try:
        interval_hours = int(body.get("interval_hours"))
    except (TypeError, ValueError):
        return None, "Вкажи інтервал у годинах (число)."
    if not (_MIN_INTERVAL_HOURS <= interval_hours <= _MAX_INTERVAL_HOURS):
        return None, f"Інтервал має бути від {_MIN_INTERVAL_HOURS} до {_MAX_INTERVAL_HOURS} год."

    property_types = [
        str(t).lower() for t in (body.get("property_types") or [])
        if str(t).lower() in ("house", "apartment")
    ] or ["house", "apartment"]

    search = {
        "transaction": "sale" if body.get("transaction") == "sale" else "rent",
        "property_types": property_types,
        "price_min": _opt_num(body.get("price_min")),
        "price_max": _opt_num(body.get("price_max")),
        "bedrooms_min": _opt_int(body.get("bedrooms_min")),
        "bedrooms_max": _opt_int(body.get("bedrooms_max")),
        "living_area_min": _opt_num(body.get("living_area_min")),
        "postal_codes": postal_codes,
        "localities": [place],
    }
    return {
        "place": place,
        "search": search,
        "interval_hours": interval_hours,
        "notify_email": notify_email,
    }, None


@app.route("/api/subscription", methods=["GET"])
def get_subscription():
    user = _authenticated_user()
    if user is None:
        return jsonify({"error": "потрібен вхід через Google"}), 401
    if not (GH_WRITE_TOKEN and GH_REPO):
        return jsonify({"error": "Розсилка ще не налаштована на сервері."}), 500

    try:
        data, _sha = read_json(GH_REPO, GH_WRITE_TOKEN, _profile_path(user["sub"]))
    except GitHubStoreError:
        log.exception("розсилка: не вдалося прочитати профіль")
        return jsonify({"error": "Не вдалося прочитати збережену розсилку."}), 502

    return jsonify({"subscription": data})


@app.route("/api/subscription", methods=["POST"])
def save_subscription():
    user = _authenticated_user()
    if user is None:
        return jsonify({"error": "потрібен вхід через Google"}), 401
    if not (GH_WRITE_TOKEN and GH_REPO):
        return jsonify({"error": "Розсилка ще не налаштована на сервері."}), 500

    body = request.get_json(force=True, silent=True) or {}
    profile, error = _validate_subscription_body(body)
    if error:
        return jsonify({"error": error}), 400

    path = _profile_path(user["sub"])
    try:
        existing, sha = read_json(GH_REPO, GH_WRITE_TOKEN, path)
    except GitHubStoreError:
        log.exception("розсилка: не вдалося прочитати попередній профіль")
        return jsonify({"error": "Не вдалося зберегти розсилку (читання)."}), 502

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    profile["google_sub"] = user["sub"]
    profile["login_email"] = user["email"]
    profile["created_utc"] = (existing or {}).get("created_utc") or now
    profile["updated_utc"] = now
    profile["last_sent_utc"] = (existing or {}).get("last_sent_utc")

    try:
        write_json(
            GH_REPO, GH_WRITE_TOKEN, path, profile,
            message=f"Розсилка: оновлено профіль {user['email']}",
            sha=sha,
        )
    except GitHubStoreError:
        log.exception("розсилка: не вдалося записати профіль")
        return jsonify({"error": "Не вдалося зберегти розсилку (запис)."}), 502

    return jsonify({"subscription": profile})


@app.route("/api/subscription", methods=["DELETE"])
def delete_subscription():
    user = _authenticated_user()
    if user is None:
        return jsonify({"error": "потрібен вхід через Google"}), 401
    if not (GH_WRITE_TOKEN and GH_REPO):
        return jsonify({"error": "Розсилка ще не налаштована на сервері."}), 500

    path = _profile_path(user["sub"])
    try:
        existing, sha = read_json(GH_REPO, GH_WRITE_TOKEN, path)
        if existing is not None:
            delete_json(
                GH_REPO, GH_WRITE_TOKEN, path, sha,
                message=f"Розсилка: скасовано для {user['email']}",
            )
    except GitHubStoreError:
        log.exception("розсилка: не вдалося скасувати профіль")
        return jsonify({"error": "Не вдалося скасувати розсилку."}), 502

    return jsonify({"ok": True})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
