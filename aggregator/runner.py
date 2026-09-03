"""
З'єднує всі частини в один робочий цикл.

Один прохід (`run_once`):
    1. для кожного сайту з config.yaml -> sites беремо scraper і збираємо оголошення;
    2. пропускаємо їх через фільтр (критерії з config.yaml -> search);
    3. записуємо в SQLite ті, яких там ще не було;
    4. про справді нові — надсилаємо сповіщення й позначаємо їх як сповіщені.

`run_forever` просто повторює це кожні N хвилин (config.yaml -> poll).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote

from . import proximus, webpage
from .config import Config
from .database import Database
from .filters import ListingFilter
from .models import Listing
from .notifier import build_notifier
from .scrapers.base import get_scraper

log = logging.getLogger(__name__)


def _dashboard_link_for_batch(page_url: str, since: str) -> str:
    """
    Адреса дошки з міткою `?since=...`, щоб посилання з листа відкривало
    дошку одразу відфільтрованою лише на оголошення з цього-таки листа
    (а не на всю історію за 90 днів). Сторінка docs/index.html сама вміє
    читати цей параметр.
    """
    if not page_url:
        return page_url
    separator = "&" if "?" in page_url else "?"
    return f"{page_url}{separator}since={quote(since)}"


def _update_fiber_availability(db: Database, listings: list[Listing], delay_seconds: float) -> None:
    """
    Для щойно доданих оголошень з відомою вулицею й номером будинку
    питає aggregator/proximus.py, чи є там оптика, і зберігає відповідь
    у базу. Якщо для цієї самої адреси відповідь уже відома (інша
    квартира в тому самому будинку) — новий запит до Proximus не
    робимо, беремо готову відповідь із бази.
    """
    for listing in listings:
        if not (listing.street and listing.house_number and listing.postal_code):
            continue

        known = db.known_fiber_status(listing.street, listing.house_number, listing.postal_code)
        if known is not None:
            db.update_fiber_info(listing.uid, *known)
            continue

        result = proximus.check_fiber(
            listing.street, listing.house_number, listing.postal_code, listing.locality
        )
        if result is not None:
            db.update_fiber_info(listing.uid, result.available, result.technology)
        if delay_seconds > 0:
            time.sleep(delay_seconds)


def run_once(config: Config) -> int:
    """Виконує один повний прохід. Повертає кількість нових оголошень."""
    listing_filter = ListingFilter(config.search)
    base_page_url = config.webpage.url if config.webpage.enabled else ""

    matched = []
    failed_sites = 0
    for site in config.sites:
        scraper = get_scraper(site)(config.search, config.http)
        try:
            fetched = list(scraper.fetch())
        except Exception:
            log.exception("scraper %r впав — пропускаємо цей сайт", site)
            failed_sites += 1
            continue
        kept = listing_filter.apply(fetched)
        log.info("%s: отримано %d, відповідають критеріям %d", site, len(fetched), len(kept))
        matched.extend(kept)

    # Якщо жоден сайт не відповів — це помилка, а не «нічого не знайшли».
    # Кидаємо виняток, щоб запуск (і в хмарі) позначився як невдалий.
    if failed_sites == len(config.sites):
        raise RuntimeError(
            f"усі сайти ({failed_sites}) не вдалося опитати — див. журнал вище "
            "(можливе блокування або зміна сайту)"
        )

    new_count = 0
    with Database(config.database_path) as db:
        if matched:
            batch_since = datetime.now(timezone.utc).isoformat(timespec="seconds")
            new_listings = db.add_new(matched)
            if new_listings:
                if config.fiber_check.enabled:
                    _update_fiber_availability(db, new_listings, config.http.request_delay_seconds)

                to_notify, duplicates = db.split_cross_site_duplicates(new_listings)
                if duplicates:
                    log.info(
                        "нових оголошень: %d, з них %d — це, судячи з усього, те саме "
                        "оголошення з іншого сайту (сповіщення не дублюємо)",
                        len(new_listings), len(duplicates),
                    )
                if to_notify:
                    log.info("сповіщаємо про %d оголошень", len(to_notify))
                    page_url = _dashboard_link_for_batch(base_page_url, batch_since)
                    notifier = build_notifier(config.notifications, page_url)
                    notifier.notify(to_notify)
                db.mark_notified(new_listings)
                new_count = len(to_notify)
            else:
                log.info("нових оголошень з минулого запуску немає")
        else:
            log.info("цього разу нічого не підійшло")

        # Веб-дошку оновлюємо щоразу, навіть коли нових оголошень немає —
        # щоб на сторінці був актуальний список і час останньої перевірки.
        if config.webpage.enabled:
            try:
                webpage.write_data(db, config.webpage, config.search.summary)
            except Exception:
                log.exception("не вдалося оновити веб-дошку")

    return new_count


def run_forever(config: Config) -> None:
    minutes = config.poll_interval_minutes
    log.info("запуск у режимі циклу: перевірка кожні %d хв", minutes)
    while True:
        try:
            run_once(config)
        except Exception:
            log.exception("прохід завершився помилкою")
        log.info("пауза %d хв до наступної перевірки", minutes)
        time.sleep(minutes * 60)
