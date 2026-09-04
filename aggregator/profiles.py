"""
Профілі розсилки — ті, що людина створює через кнопку "✉ Розсилка" на
дошці (docs/index.html), а сервер (server/app.py) зберігає файлом
`profiles/<google-sub>.json` прямо в цьому репозиторії.

Тут — лише читання цих файлів і визначення, кому вже час перевіряти
нові оголошення. Саме надсилання листів — у aggregator/runner.py
(run_profiles), яка бере ці профілі й пускає в хід той самий
scraper/filter/notifier, що й основний потік.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import SearchCriteria

log = logging.getLogger(__name__)


@dataclass
class Profile:
    path: Path
    google_sub: str
    notify_email: str
    interval_hours: int
    search: SearchCriteria
    last_sent_utc: Optional[str]

    @property
    def id(self) -> str:
        """Стабільний ідентифікатор профілю — ім'я файлу без .json."""
        return self.path.stem

    def is_due(self, now: Optional[datetime] = None) -> bool:
        """Чи минуло достатньо часу відколи цей профіль востаннє перевіряли."""
        if not self.last_sent_utc:
            return True
        now = now or datetime.now(timezone.utc)
        try:
            last = datetime.fromisoformat(self.last_sent_utc)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return now - last >= timedelta(hours=self.interval_hours)


def _parse_profile(path: Path) -> Optional[Profile]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        search = SearchCriteria(**(data.get("search") or {}))
        notify_email = str(data["notify_email"]).strip()
        interval_hours = int(data["interval_hours"])
        if not notify_email:
            raise ValueError("порожня notify_email")
    except Exception:
        log.warning("профіль %s пошкоджений або неповний — пропускаю", path, exc_info=True)
        return None

    return Profile(
        path=path,
        google_sub=str(data.get("google_sub") or ""),
        notify_email=notify_email,
        interval_hours=interval_hours,
        search=search,
        last_sent_utc=data.get("last_sent_utc"),
    )


def load_profiles(directory: "str | Path" = "profiles") -> list[Profile]:
    """Читає всі profiles/*.json. Биті чи неповні файли пропускає (з попередженням у журнал)."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return []
    profiles: list[Profile] = []
    for path in sorted(dir_path.glob("*.json")):
        profile = _parse_profile(path)
        if profile is not None:
            profiles.append(profile)
    return profiles


def mark_checked(profile: Profile, when: Optional[datetime] = None) -> None:
    """
    Записує "перевірено щойно" (last_sent_utc) назад у файл профілю —
    незалежно від того, чи знайшлось цього разу щось нове (щоб
    інтервал рахувався від моменту перевірки, а не лише від
    успішного надсилання листа).
    """
    when = when or datetime.now(timezone.utc)
    try:
        data = json.loads(profile.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data["last_sent_utc"] = when.isoformat(timespec="seconds")
    profile.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
