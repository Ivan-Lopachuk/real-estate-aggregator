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

import dataclasses
import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote

from . import profiles as profiles_module
from . import proximus, webpage
from .config import Config
from .database import Database
from .filters import ListingFilter
from .models import Listing
from .notifier import EmailNotifier, build_notifier
from .scrapers.base import get_scraper

log = logging.getLogger(__name__)


def _dashboard_link_for_batch(page_url: str, since: str) -> str:
    """
    Адреса дошки з міткою `?since=...`, щоб посилання з листа відкривало
    дошку одразу відфільтрованою лише на оголошення з цього-таки листа
    (а не на всю історію за 90 днів). Сторінка docs/index.html сама вміє
    читати цей параметр.

    Працює надійно лише коли всі оголошення в листі щойно вперше
    з'явились у базі за ЦЕЙ прохід (так і є в run_once) — тому для
    основного, єдиного пошуку з config.yaml.
    """
    if not page_url:
        return page_url
    separator = "&" if "?" in page_url else "?"
    return f"{page_url}{separator}since={quote(since)}"


def _dashboard_link_for_uids(page_url: str, uids: list[str]) -> str:
    """
    Те саме призначення, що й _dashboard_link_for_batch, але для
    профілів розсилки (run_profiles): оголошення, нове для конкретного
    профілю, могло потрапити в базу набагато раніше — знайшов його
    основний пошук чи інший профіль. Тоді first_seen_utc старіше за
    момент цього запуску, і фільтр за часом (?since=) на дошці
    помилково показав би "нічого немає". Тут натомість передаємо
    точний перелік id — дошка показує рівно ці оголошення, незалежно
    від того, коли їх уперше побачили.
    """
    if not page_url or not uids:
        return page_url
    separator = "&" if "?" in page_url else "?"
    return f"{page_url}{separator}ids={quote(','.join(uids))}"


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


def run_profiles(config: Config, profiles_dir: str = "profiles") -> int:
    """
    Окремий прохід — незалежний від run_once() і config.yaml -> search.

    Проходить по всіх збережених профілях розсилки (profiles/*.json,
    їх створює людина через кнопку "✉ Розсилка" на дошці — див.
    aggregator/profiles.py й server/app.py). Для кожного профілю, кому
    вже час (свій інтервал у годинах): шукає нові оголошення за ЙОГО
    критеріями й шле лист на ЙОГО пошту — тим самим SMTP-акаунтом, що
    й основні сповіщення з config.yaml, лише з іншим отримувачем.

    Повертає, скільком листам за профілями зрештою пощастило піти.
    """
    if config.notifications.email is None:
        log.info("розсилка за профілями: SMTP не налаштовано в config.yaml — пропускаю")
        return 0

    due = [p for p in profiles_module.load_profiles(profiles_dir) if p.is_due()]
    if not due:
        return 0
    log.info("розсилка за профілями: перевіряю %d профіл(ів)", len(due))

    base_page_url = config.webpage.url if config.webpage.enabled else ""
    sent_count = 0
    any_new = False
    with Database(config.database_path) as db:
        for profile in due:
            listing_filter = ListingFilter(profile.search)
            matched: list[Listing] = []
            for site in config.sites:
                scraper = get_scraper(site)(profile.search, config.http)
                try:
                    fetched = list(scraper.fetch())
                except Exception:
                    log.exception("профіль %s: scraper %r впав — пропускаю сайт", profile.id, site)
                    continue
                matched.extend(listing_filter.apply(fetched))

            if matched:
                db.add_new(matched)  # спільна таблиця — дедуплікація й кеш оптики як завжди

            new_for_profile = db.new_for_profile(profile.id, matched)
            if new_for_profile:
                to_notify, _duplicates = db.split_cross_site_duplicates(new_for_profile)
                if to_notify:
                    email_settings = dataclasses.replace(
                        config.notifications.email, to_addresses=[profile.notify_email]
                    )
                    page_url = _dashboard_link_for_uids(base_page_url, [l.uid for l in to_notify])
                    try:
                        EmailNotifier(email_settings, page_url).notify(to_notify)
                        sent_count += len(to_notify)
                        any_new = True
                    except Exception:
                        log.exception("профіль %s: не вдалося надіслати лист", profile.id)
                        continue  # не позначаємо — спробуємо знову наступного разу
                db.mark_notified_for_profile(profile.id, new_for_profile)

            profiles_module.mark_checked(profile)

        # Щойно знайдені за профілями оголошення вже лежать у спільній
        # таблиці (add_new вище) — лишається оновити docs/data.json, щоб
        # посилання в листі («дошка з позначкою since=...») справді щось
        # показало, а не порожню сторінку.
        if any_new and config.webpage.enabled:
            try:
                webpage.write_data(db, config.webpage, config.search.summary)
            except Exception:
                log.exception("розсилка за профілями: не вдалося оновити веб-дошку")

    return sent_count


def run_forever(config: Config) -> None:
    minutes = config.poll_interval_minutes
    log.info("запуск у режимі циклу: перевірка кожні %d хв", minutes)
    while True:
        try:
            run_once(config)
        except Exception:
            log.exception("прохід завершився помилкою")
        try:
            run_profiles(config)
        except Exception:
            log.exception("розсилка за профілями завершилась помилкою")
        log.info("пауза %d хв до наступної перевірки", minutes)
        time.sleep(minutes * 60)
