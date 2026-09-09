"""
Підписки на сайт (хто має право ним користуватись).

Оплати немає — доступ вмикає власник вручну. Цей модуль тримає лише
*логіку* (чиста робота зі словниками, без мережі й без файлів), щоб її
було легко тестувати. Сам файл підписок читає й пише сервер
(`server/app.py`) — одним JSON-файлом у репозиторії:

    subscriptions/index.json

Формат файлу — словник, ключ якого — пошта людини (маленькими літерами):

    {
      "person@gmail.com": {
        "status": "active",          # "active" або "revoked"
        "plan": "pro",
        "granted_by": "owner@gmail.com",
        "granted_utc": "2026-09-09T10:00:00+00:00",
        "expires_utc": "2026-12-31T00:00:00+00:00",   # або null = безстроково
        "note": ""
      },
      ...
    }

Адміни (список пошт у змінній середовища ADMIN_EMAILS) завжди мають
доступ — незалежно від вмісту цього файлу.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

# Дозволені значення поля "status".
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"


def normalize_email(email: Optional[str]) -> str:
    """Пошта як ключ: без пробілів по краях і маленькими літерами."""
    return (email or "").strip().lower()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """ISO-рядок -> datetime у UTC. None / сміття -> None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_active(entry: Optional[dict], now: Optional[datetime] = None) -> bool:
    """
    Чи діє підписка прямо зараз: статус "active" і (термін не заданий
    або ще не минув). Порожній запис / знята підписка -> False.
    """
    if not entry or entry.get("status") != STATUS_ACTIVE:
        return False
    expires = _parse_dt(entry.get("expires_utc"))
    if expires is None:
        return True  # безстроково
    now = now or datetime.now(timezone.utc)
    return now < expires


def entitlement_for(
    store: Optional[dict],
    email: Optional[str],
    admin_emails: Iterable[str],
    now: Optional[datetime] = None,
) -> dict:
    """
    Підсумок прав для однієї людини — саме це сервер віддає фронтенду
    (`GET /api/me`), щоб той вирішив, який екран показати.

    Повертає:
        {
          "active":     True/False — чи пускати на сайт,
          "is_admin":   True/False,
          "status":     "active" / "revoked" / "none",
          "plan":       рядок або None,
          "expires_utc": рядок або None,
          "note":       рядок,
        }
    """
    email_n = normalize_email(email)
    admins = {normalize_email(a) for a in admin_emails if normalize_email(a)}
    is_admin = email_n in admins

    entry = (store or {}).get(email_n) or {}
    active = is_admin or is_active(entry, now)

    if is_admin:
        status = STATUS_ACTIVE
        plan = entry.get("plan") or "admin"
    else:
        status = entry.get("status") or "none"
        plan = entry.get("plan") or None

    return {
        "active": active,
        "is_admin": is_admin,
        "status": status,
        "plan": plan,
        "expires_utc": entry.get("expires_utc"),
        "note": entry.get("note") or "",
    }


def upsert(
    store: Optional[dict],
    email: str,
    *,
    status: str = STATUS_ACTIVE,
    plan: str = "pro",
    expires_utc: Optional[str] = None,
    note: str = "",
    granted_by: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """
    Додає або оновлює підписку. Повертає НОВИЙ словник-сховище (старий
    не змінює), щоб виклик був передбачуваним.
    """
    email_n = normalize_email(email)
    if not email_n:
        raise ValueError("порожня пошта")
    if status not in (STATUS_ACTIVE, STATUS_REVOKED):
        raise ValueError(f"невідомий статус: {status!r}")
    if expires_utc and _parse_dt(expires_utc) is None:
        raise ValueError(f"не зрозумів дату закінчення: {expires_utc!r}")

    now = now or datetime.now(timezone.utc)
    updated = dict(store or {})
    previous = updated.get(email_n) or {}
    updated[email_n] = {
        "status": status,
        "plan": plan or "pro",
        "granted_by": granted_by or previous.get("granted_by") or "",
        "granted_utc": previous.get("granted_utc") or now.isoformat(timespec="seconds"),
        "updated_utc": now.isoformat(timespec="seconds"),
        "expires_utc": expires_utc or None,
        "note": note or "",
    }
    return updated


def remove(store: Optional[dict], email: str) -> dict:
    """Прибирає підписку зовсім. Повертає новий словник-сховище."""
    email_n = normalize_email(email)
    updated = dict(store or {})
    updated.pop(email_n, None)
    return updated
