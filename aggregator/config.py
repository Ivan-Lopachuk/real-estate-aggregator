"""
Читання та перевірка файлу config.yaml.

Головна ідея проєкту: жоден критерій пошуку не «зашитий» у коді.
Усе береться звідси. `Config.load("config.yaml")` повертає готовий
об'єкт `Config`, а якщо у файлі є помилка — кидає зрозумілий
`ConfigError` із поясненням, що саме не так.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class ConfigError(Exception):
    """Кидається, коли config.yaml відсутній або заповнений неправильно."""


# --- дрібні помічники для акуратного приведення типів -----------------

def _num(value) -> Optional[float]:
    """None -> None, інакше число з рухомою комою."""
    return None if value is None else float(value)


def _int(value) -> Optional[int]:
    return None if value is None else int(value)


def _load_dotenv(directory: Path) -> None:
    """
    Якщо поруч із config.yaml лежить файл `.env` — підвантажити з нього
    змінні середовища (рядки виду KEY=VALUE).

    Потрібно, щоб пароль SMTP був доступний не лише у відкритому терміналі,
    а й при автоматичному запуску за розкладом (Планувальник завдань Windows).
    Уже задані змінні середовища мають пріоритет і не перезаписуються.
    """
    env_file = directory / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# --- окремі шматки налаштувань --------------------------------------

@dataclass
class SearchCriteria:
    """Розділ `search:` з config.yaml — що саме шукаємо."""
    transaction: str = "sale"
    property_types: list[str] = field(default_factory=lambda: ["house", "apartment"])
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    bedrooms_max: Optional[int] = None
    living_area_min: Optional[float] = None
    postal_codes: list[str] = field(default_factory=list)
    localities: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """
        Короткий людський опис критеріїв — для листа і веб-сторінки.

        Якщо задана лише одна межа діапазону (напр. лише price_max, без
        price_min — типово для запитів через AI-чат, де людина рідко
        називає обидві межі) — не показуємо "…", а пишемо "до X"/"від X".
        """
        parts: list[str] = ["оренда" if self.transaction == "rent" else "купівля"]

        def _fmt(n: float) -> str:
            return f"{n:,.0f}".replace(",", " ")

        if self.price_min is not None and self.price_max is not None:
            parts.append(f"{_fmt(self.price_min)}–{_fmt(self.price_max)} €")
        elif self.price_max is not None:
            parts.append(f"до {_fmt(self.price_max)} €")
        elif self.price_min is not None:
            parts.append(f"від {_fmt(self.price_min)} €")

        if self.bedrooms_min is not None and self.bedrooms_max is not None:
            if self.bedrooms_min == self.bedrooms_max:
                parts.append(f"{self.bedrooms_min} спалень")
            else:
                parts.append(f"{self.bedrooms_min}–{self.bedrooms_max} спалень")
        elif self.bedrooms_max is not None:
            parts.append(f"до {self.bedrooms_max} спалень")
        elif self.bedrooms_min is not None:
            parts.append(f"від {self.bedrooms_min} спалень")

        if self.living_area_min is not None:
            parts.append(f"від {self.living_area_min:.0f} м²")
        if self.localities:
            parts.append(", ".join(self.localities))
        elif self.postal_codes:
            parts.append(", ".join(self.postal_codes))
        return " · ".join(parts)


def _parse_search(s: dict) -> SearchCriteria:
    """
    Розбирає розділ `search:` у SearchCriteria. Винесено окремою
    функцією (а не лишено всередині Config.load), бо це саме той шматок
    налаштувань, який потрібно перевірити ОКРЕМО від решти config.yaml —
    напр. `scripts/apply_search_criteria.py` звіряє лише нові критерії
    пошуку і не має чіпати пошту/сповіщення.
    """
    search = SearchCriteria(
        transaction=str(s.get("transaction", "sale")).lower(),
        property_types=[str(t).lower() for t in (s.get("property_types") or ["house", "apartment"])],
        price_min=_num(s.get("price_min")),
        price_max=_num(s.get("price_max")),
        bedrooms_min=_int(s.get("bedrooms_min")),
        bedrooms_max=_int(s.get("bedrooms_max")),
        living_area_min=_num(s.get("living_area_min")),
        postal_codes=[str(z) for z in (s.get("postal_codes") or [])],
        localities=[str(x) for x in (s.get("localities") or [])],
    )
    if search.transaction not in ("sale", "rent"):
        raise ConfigError("search.transaction має бути 'sale' або 'rent'.")
    return search


@dataclass
class HttpSettings:
    """Розділ `http:` — як поводитися з мережею."""
    request_delay_seconds: float = 1.0
    max_pages: int = 10
    timeout_seconds: int = 20
    # Реалістичний User-Agent потрібен, бо Immoweb за захистом Cloudflare
    # і відхиляє запити «без браузера».
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )


@dataclass
class EmailSettings:
    """Розділ `notifications.email:` — куди і як слати листи."""
    smtp_host: str
    smtp_port: int
    username: str
    from_address: str
    to_addresses: list[str]
    use_tls: bool = True          # STARTTLS (напр. Gmail, порт 587)
    use_ssl: bool = False         # одразу SSL-з'єднання (напр. ukr.net, порт 465)
    password_env: str = "AGGREGATOR_SMTP_PASSWORD"

    @property
    def password(self) -> str:
        """Пароль береться зі змінної середовища, а не з файлу."""
        pw = os.environ.get(self.password_env)
        if not pw:
            raise ConfigError(
                f"Змінна середовища {self.password_env!r} не задана. "
                "У ній має бути пароль SMTP (для Gmail — App Password). "
                "Див. README.md, розділ «Email-сповіщення»."
            )
        return pw


@dataclass
class TelegramSettings:
    """
    Розділ `notifications.telegram:` — сповіщення в Telegram через
    власного бота (безкоштовно, без обмежень OpenRouter/SMTP).

    chat_id можна задати або тут, або через змінну середовища
    AGGREGATOR_TELEGRAM_CHAT_ID (як і адреса пошти вище) — корисно,
    якщо не хочете тримати навіть id чату у публічному репозиторії.
    """
    chat_id: str
    bot_token_env: str = "AGGREGATOR_TELEGRAM_BOT_TOKEN"

    @property
    def bot_token(self) -> str:
        """Токен бота береться зі змінної середовища, а не з файлу."""
        token = os.environ.get(self.bot_token_env)
        if not token:
            raise ConfigError(
                f"Змінна середовища {self.bot_token_env!r} не задана. "
                "У ній має бути токен Telegram-бота від @BotFather. "
                "Див. README.md, розділ «Telegram-сповіщення»."
            )
        return token


def parse_notification_methods(raw: str) -> set[str]:
    """
    Розбирає `notifications.method` на множину каналів. Підтримує:
      * старі значення "console" / "email" / "both" (=console+email) —
        щоб не ламати вже наявні config.yaml;
      * "telegram" — новий канал;
      * будь-яку комбінацію через кому, напр. "email,telegram" або
        "console,email,telegram".
    """
    raw = raw.lower().strip()
    if raw == "both":
        return {"console", "email"}
    return {token.strip() for token in raw.split(",") if token.strip()}


_VALID_NOTIFICATION_METHODS = {"console", "email", "telegram"}


@dataclass
class NotificationSettings:
    """Розділ `notifications:`."""
    method: str = "console"                 # console | email | telegram | both | будь-яка комбінація через кому
    email: Optional[EmailSettings] = None
    telegram: Optional[TelegramSettings] = None


@dataclass
class FiberCheckSettings:
    """
    Розділ `fiber_check:` — автоматична перевірка, чи є за адресою
    оголошення оптоволоконний інтернет Proximus (неофіційний, але
    робочий механізм — див. aggregator/proximus.py).
    """
    enabled: bool = False


@dataclass
class WebpageSettings:
    """
    Розділ `webpage:` — генерація файлу списку для веб-дошки (GitHub Pages).

    Якщо `enabled`, після кожного проходу програма перезаписує
    `<output_dir>/data.json` усіма оголошеннями з бази. Готова сторінка
    `<output_dir>/index.html` читає цей файл і показує список, позначаючи
    вже відкриті оголошення.
    """
    enabled: bool = False
    output_dir: str = "docs"
    url: str = ""            # публічна адреса дошки — потрапляє в лист


# --- головний об'єкт налаштувань ------------------------------------

@dataclass
class Config:
    sites: list[str]
    search: SearchCriteria
    http: HttpSettings
    notifications: NotificationSettings
    database_path: Path
    poll_interval_minutes: int
    webpage: WebpageSettings = field(default_factory=WebpageSettings)
    fiber_check: FiberCheckSettings = field(default_factory=FiberCheckSettings)

    @classmethod
    def load(cls, path: "str | Path") -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Файл налаштувань не знайдено: {path}. "
                "Він має лежати поруч із main.py."
            )

        _load_dotenv(path.resolve().parent)

        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ConfigError("config.yaml має бути набором налаштувань (ключ: значення).")

        # -- sites --
        sites = data.get("sites") or []
        if not sites:
            raise ConfigError("config.yaml: у розділі 'sites' має бути хоча б один сайт.")

        # -- search --
        search = _parse_search(data.get("search") or {})

        # -- http --
        h = data.get("http") or {}
        http = HttpSettings(
            request_delay_seconds=float(h.get("request_delay_seconds", 1.0)),
            max_pages=int(h.get("max_pages", 10)),
            timeout_seconds=int(h.get("timeout_seconds", 20)),
        )
        if h.get("user_agent"):
            http.user_agent = str(h["user_agent"])

        # -- notifications --
        n = data.get("notifications") or {}
        email_raw = n.get("email") or {}
        email: Optional[EmailSettings] = None
        if email_raw:
            # Адреса пошти може задаватись або в config.yaml, або (щоб її не
            # тримати у публічному репозиторії) у змінних середовища / .env.
            # Змінна середовища має пріоритет.
            username = (
                os.environ.get("AGGREGATOR_SMTP_USERNAME")
                or str(email_raw.get("username") or "")
            ).strip()
            if not username:
                raise ConfigError(
                    "notifications.email: не задано адресу відправника — вкажіть "
                    "'username' у config.yaml або змінну AGGREGATOR_SMTP_USERNAME."
                )
            from_address = (
                os.environ.get("AGGREGATOR_EMAIL_FROM")
                or str(email_raw.get("from_address") or "")
                or username
            ).strip()
            to_env = os.environ.get("AGGREGATOR_EMAIL_TO")
            if to_env:
                to_addresses = [a.strip() for a in to_env.split(",") if a.strip()]
            else:
                to_addresses = [str(a) for a in (email_raw.get("to_addresses") or [])]
            try:
                email = EmailSettings(
                    smtp_host=str(email_raw["smtp_host"]),
                    smtp_port=int(email_raw["smtp_port"]),
                    username=username,
                    from_address=from_address,
                    to_addresses=to_addresses,
                    use_tls=bool(email_raw.get("use_tls", True)),
                    use_ssl=bool(email_raw.get("use_ssl", False)),
                    password_env=str(email_raw.get("password_env", "AGGREGATOR_SMTP_PASSWORD")),
                )
            except KeyError as missing:
                raise ConfigError(f"notifications.email: бракує обов'язкового ключа {missing}.")
            if not email.to_addresses:
                raise ConfigError(
                    "notifications.email: не задано отримувача — вкажіть 'to_addresses' "
                    "у config.yaml або змінну AGGREGATOR_EMAIL_TO."
                )

        telegram_raw = n.get("telegram") or {}
        telegram: Optional[TelegramSettings] = None
        if telegram_raw:
            chat_id = (
                os.environ.get("AGGREGATOR_TELEGRAM_CHAT_ID")
                or str(telegram_raw.get("chat_id") or "")
            ).strip()
            if not chat_id:
                raise ConfigError(
                    "notifications.telegram: не задано 'chat_id' — вкажіть його "
                    "у config.yaml або змінну AGGREGATOR_TELEGRAM_CHAT_ID."
                )
            telegram = TelegramSettings(
                chat_id=chat_id,
                bot_token_env=str(telegram_raw.get("bot_token_env", "AGGREGATOR_TELEGRAM_BOT_TOKEN")),
            )

        method_raw = str(n.get("method", "console")).lower()
        methods = parse_notification_methods(method_raw)
        unknown = methods - _VALID_NOTIFICATION_METHODS
        if not methods or unknown:
            raise ConfigError(
                "notifications.method має складатися з 'console', 'email', 'telegram' "
                "(через кому) або бути 'both' (=console+email)."
            )
        if "email" in methods and email is None:
            raise ConfigError(
                "notifications.method включає 'email', але розділ 'email:' не заповнено."
            )
        if "telegram" in methods and telegram is None:
            raise ConfigError(
                "notifications.method включає 'telegram', але розділ 'telegram:' не заповнено."
            )

        notifications = NotificationSettings(
            method=method_raw,
            email=email,
            telegram=telegram,
        )

        db = data.get("database") or {}
        poll = data.get("poll") or {}

        w = data.get("webpage") or {}
        webpage = WebpageSettings(
            enabled=bool(w.get("enabled", False)),
            output_dir=str(w.get("output_dir", "docs")),
            url=str(w.get("url") or "").strip(),
        )

        fc = data.get("fiber_check") or {}
        fiber_check = FiberCheckSettings(enabled=bool(fc.get("enabled", False)))

        return cls(
            sites=[str(x).lower() for x in sites],
            search=search,
            http=http,
            notifications=notifications,
            database_path=Path(db.get("path", "listings.db")),
            poll_interval_minutes=int(poll.get("interval_minutes", 30)),
            webpage=webpage,
            fiber_check=fiber_check,
        )


def load_search_criteria(path: "str | Path") -> SearchCriteria:
    """
    Читає й перевіряє ЛИШЕ розділ `search:` із config.yaml — на відміну
    від Config.load(), не чіпає пошту й інші розділи. Використовується
    для перевірки нових критеріїв пошуку (напр. у
    scripts/apply_search_criteria.py), де налаштування пошти можуть бути
    ще не заповнені, і це не має заважати.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Файл налаштувань не знайдено: {path}.")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError("config.yaml має бути набором налаштувань (ключ: значення).")
    return _parse_search(data.get("search") or {})
