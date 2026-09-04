"""
Зберігання оголошень у файлі SQLite.

Призначення — пам'ять між запусками. Коли програма знаходить оголошення,
вона запитує базу: «а це вже було?». Якщо ні — запис додається, і саме про
такі (справді нові) оголошення надсилається сповіщення. Завдяки цьому
однакове оголошення не «дзвонить» вам щоразу.

Оскільки сайтів кілька, той самий рієлтор часто виставляє ту саму
нерухомість одразу на декількох із них — з різними номерами оголошення.
Щоб не сповіщати про, по суті, одне й те саме двічі, тут же є проста
перевірка «схожості»: якщо в іншого сайту вже є оголошення з тим самим
типом угоди, типом житла, поштовим індексом і ціною (і, якщо відома,
такою самою житловою площею) — нове оголошення все одно зберігається в
базі (щоб мати посилання на обидва сайти), але сповіщення про нього не
дублюється. Це евристика, не гарантія: теоретично дві різні квартири в
одному будинку можуть випадково збігтися за цими ознаками.

SQLite входить до стандартної бібліотеки Python (модуль sqlite3) —
жодних серверів баз даних ставити не треба, це просто один файл.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import dedup
from .models import Listing

# Стовпець назвали transaction_kind, бо TRANSACTION — службове слово SQL.
# Базовий вигляд таблиці для НОВОЇ бази. Якщо ви оновили програму, а
# listings.db у вас уже є з попередньої версії — нові стовпці, яких тут
# бракує, самі додаються нижче в _MIGRATIONS (SQLite не додає стовпці
# заднім числом через CREATE TABLE IF NOT EXISTS, коли таблиця вже є).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    uid              TEXT PRIMARY KEY,
    site             TEXT NOT NULL,
    site_listing_id  TEXT NOT NULL,
    url              TEXT NOT NULL,
    title            TEXT,
    price            REAL,
    currency         TEXT,
    transaction_kind TEXT,
    property_type    TEXT,
    bedrooms         INTEGER,
    living_area      REAL,
    locality         TEXT,
    postal_code      TEXT,
    first_seen_utc   TEXT NOT NULL,
    notified         INTEGER NOT NULL DEFAULT 0
);

-- Окрема таблиця для профілів розсилки (aggregator/profiles.py):
-- "чи вже сповіщали ЦЕЙ профіль про ЦЕ оголошення". Свідомо окремо
-- від listings.notified (той стовпець — лише для основного
-- сповіщення з config.yaml), бо різні профілі можуть побачити те
-- саме оголошення в різний час і кожному з них воно все одно нове.
CREATE TABLE IF NOT EXISTS profile_notified (
    profile_id   TEXT NOT NULL,
    listing_uid  TEXT NOT NULL,
    notified_utc TEXT NOT NULL,
    PRIMARY KEY (profile_id, listing_uid)
);
"""

# Стовпці, додані вже після першого релізу. Ключ — назва, значення — тип
# у SQL. При кожному відкритті бази перевіряємо, чи вони вже є, і
# додаємо, якщо бракує (ALTER TABLE ADD COLUMN) — щоб оновлення програми
# не «губило» вже зібрані оголошення в старій базі.
_MIGRATIONS: dict[str, str] = {
    "duplicate_of": "TEXT",
    "street": "TEXT",
    "house_number": "TEXT",
    "fiber_available": "INTEGER",
    "fiber_technology": "TEXT",
    "photo_url": "TEXT",
    "extra_costs": "REAL",
}

# Скільки днів «пам'ятаємо» оголошення для пошуку схожості на іншому сайті.
# Довше не має сенсу — за цей час оголошення зазвичай уже здають/продають.
_DUPLICATE_WINDOW_DAYS = 60

# Сама евристика "це, ймовірно, та сама нерухомість" — спільна з живим
# AI-пошуком (server/app.py), див. aggregator/dedup.py.
_duplicate_lookup_key = dedup.duplicate_key
_values_compatible = dedup.values_compatible
_LIVING_AREA_TOLERANCE = dedup.LIVING_AREA_TOLERANCE


class Database:
    """Тонка обгортка навколо sqlite3. Підтримує `with Database(path) as db:`."""

    def __init__(self, path: "str | Path") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Додає стовпці з _MIGRATIONS, яких ще немає в наявній базі."""
        existing = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(listings)")
        }
        for column, sql_type in _MIGRATIONS.items():
            if column not in existing:
                self._conn.execute(f"ALTER TABLE listings ADD COLUMN {column} {sql_type}")

    # -- підтримка контекстного менеджера --
    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # -- операції --
    def is_known(self, uid: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM listings WHERE uid = ? LIMIT 1", (uid,)
        ).fetchone()
        return row is not None

    def add_new(self, listings: Iterable[Listing]) -> list[Listing]:
        """
        Додає до бази ті оголошення, яких там ще не було.
        Повертає список саме нових (щойно доданих) — їх і треба сповістити.
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        new: list[Listing] = []
        for listing in listings:
            if self.is_known(listing.uid):
                continue
            self._conn.execute(
                """
                INSERT INTO listings (
                    uid, site, site_listing_id, url, title, price, extra_costs, currency,
                    transaction_kind, property_type, bedrooms, living_area,
                    locality, postal_code, street, house_number, photo_url,
                    first_seen_utc, notified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    listing.uid, listing.site, listing.site_listing_id, listing.url,
                    listing.title, listing.price, listing.extra_costs, listing.currency,
                    listing.transaction, listing.property_type, listing.bedrooms,
                    listing.living_area, listing.locality, listing.postal_code,
                    listing.street, listing.house_number, listing.photo_url, now,
                ),
            )
            new.append(listing)
        self._conn.commit()
        return new

    def mark_notified(self, listings: Iterable[Listing]) -> None:
        """Позначає, що про ці оголошення сповіщення вже надіслано."""
        self._conn.executemany(
            "UPDATE listings SET notified = 1 WHERE uid = ?",
            [(l.uid,) for l in listings],
        )
        self._conn.commit()

    def new_for_profile(self, profile_id: str, listings: Iterable[Listing]) -> list[Listing]:
        """
        З цих оголошень — ті, про які ЩЕ не сповіщали саме цей профіль
        розсилки (незалежно від того, чи оголошення вже є в базі
        завдяки іншому профілю чи основному пошуку).
        """
        listings = list(listings)
        if not listings:
            return []
        uids = [l.uid for l in listings]
        placeholders = ",".join("?" for _ in uids)
        rows = self._conn.execute(
            f"""
            SELECT listing_uid FROM profile_notified
            WHERE profile_id = ? AND listing_uid IN ({placeholders})
            """,
            (profile_id, *uids),
        ).fetchall()
        already = {row["listing_uid"] for row in rows}
        return [l for l in listings if l.uid not in already]

    def mark_notified_for_profile(self, profile_id: str, listings: Iterable[Listing]) -> None:
        """Позначає, що цей профіль розсилки вже бачив ці оголошення."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO profile_notified (profile_id, listing_uid, notified_utc)
            VALUES (?, ?, ?)
            """,
            [(profile_id, l.uid, now) for l in listings],
        )
        self._conn.commit()

    def known_fiber_status(
        self, street: str, house_number: str, postal_code: str
    ) -> Optional[tuple[Optional[bool], Optional[str]]]:
        """
        Чи вже перевіряли оптику для цієї самої адреси (напр. інша
        квартира в тому самому будинку)? Якщо так — повертає
        (fiber_available, fiber_technology) без нового звернення до
        Proximus. None, якщо такої адреси в базі ще немає.
        """
        row = self._conn.execute(
            """
            SELECT fiber_available, fiber_technology FROM listings
            WHERE street = ? AND house_number = ? AND postal_code = ?
              AND fiber_available IS NOT NULL
            LIMIT 1
            """,
            (street, house_number, postal_code),
        ).fetchone()
        if row is None:
            return None
        return bool(row["fiber_available"]), row["fiber_technology"]

    def update_fiber_info(
        self, uid: str, available: Optional[bool], technology: Optional[str]
    ) -> None:
        """Записує результат перевірки оптики Proximus для оголошення."""
        self._conn.execute(
            "UPDATE listings SET fiber_available = ?, fiber_technology = ? WHERE uid = ?",
            (None if available is None else int(available), technology, uid),
        )
        self._conn.commit()

    def split_cross_site_duplicates(
        self, listings: Iterable[Listing]
    ) -> tuple[list[Listing], list[Listing]]:
        """
        Ділить щойно додані (через add_new) оголошення на дві групи:

        - перша — про них варто сповістити;
        - друга — «дублікати»: судячи з ціни, типу житла, поштового
          індексу (і площі, якщо відома), це, найімовірніше, та сама
          нерухомість, що вже є в базі з ІНШОГО сайту (з цього самого
          проходу або з попереднього — не старіше `_DUPLICATE_WINDOW_DAYS`
          днів). Для кожного дубліката в базі записується uid оригіналу
          (стовпець `duplicate_of`) — оголошення нікуди не зникає, просто
          повторне сповіщення про нього не надсилається.
        """
        listings = list(listings)
        all_uids_this_batch = {l.uid for l in listings}

        to_notify: list[Listing] = []
        duplicates: list[Listing] = []
        confirmed_unique: list[Listing] = []
        pairs: list[tuple[str, str]] = []  # (uid оригіналу, uid дубліката)

        for candidate in listings:
            original_uid = self._find_older_duplicate(
                candidate, exclude_uids=all_uids_this_batch
            ) or self._find_batch_duplicate(candidate, confirmed_unique)

            if original_uid:
                pairs.append((original_uid, candidate.uid))
                duplicates.append(candidate)
            else:
                confirmed_unique.append(candidate)
                to_notify.append(candidate)

        if pairs:
            self._conn.executemany(
                "UPDATE listings SET duplicate_of = ? WHERE uid = ?", pairs
            )
            self._conn.commit()

        return to_notify, duplicates

    def _find_older_duplicate(
        self, listing: Listing, exclude_uids: set[str]
    ) -> Optional[str]:
        """Шукає схоже оголошення з іншого сайту, збережене раніше в базі."""
        key = _duplicate_lookup_key(listing)
        if key is None:
            return None
        transaction, property_type, postal_code, price = key

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_DUPLICATE_WINDOW_DAYS)
        ).isoformat(timespec="seconds")
        exclude = exclude_uids or {listing.uid}
        placeholders = ",".join("?" for _ in exclude)
        rows = self._conn.execute(
            f"""
            SELECT uid, bedrooms, living_area FROM listings
            WHERE site != ? AND uid NOT IN ({placeholders})
              AND transaction_kind = ? AND property_type = ?
              AND postal_code = ? AND price = ?
              AND first_seen_utc >= ?
            """,
            (listing.site, *exclude, transaction, property_type, postal_code, price, cutoff),
        ).fetchall()

        for row in rows:
            if _values_compatible(listing.bedrooms, row["bedrooms"]) and _values_compatible(
                listing.living_area, row["living_area"], _LIVING_AREA_TOLERANCE
            ):
                return row["uid"]
        return None

    @staticmethod
    def _find_batch_duplicate(
        candidate: Listing, confirmed_unique: list[Listing]
    ) -> Optional[str]:
        """Шукає схоже оголошення серед уже розглянутих у цьому ж проході."""
        original = dedup.find_duplicate_in_batch(candidate, confirmed_unique)
        return original.uid if original is not None else None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]

    def recent_listings(self, days: int = 90) -> list[sqlite3.Row]:
        """
        Усі оголошення, вперше побачені за останні `days` днів,
        від найновіших до найстаріших. Використовується для веб-дошки.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds")
        return list(
            self._conn.execute(
                "SELECT * FROM listings WHERE first_seen_utc >= ? "
                "ORDER BY first_seen_utc DESC",
                (cutoff,),
            ).fetchall()
        )
