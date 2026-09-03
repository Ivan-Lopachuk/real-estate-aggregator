"""
Сповіщення про нові оголошення.

Є три способи (обирається в config.yaml -> notifications.method):
    * ConsoleNotifier — просто друкує список у терміналі (зручно для тестів);
    * EmailNotifier   — надсилає лист через smtplib (стандартна бібліотека);
    * MultiNotifier    — робить і те, і те ("both").

Усі мають однаковий метод `notify(listings)`, тож решті програми байдуже,
який саме спосіб обрано.
"""

from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Sequence

from .config import EmailSettings, NotificationSettings
from .models import Listing

log = logging.getLogger(__name__)


# --- формування тексту повідомлення --------------------------------

def _format_listing(l: Listing) -> str:
    price = f"{l.price:,.0f} {l.currency}" if l.price is not None else "ціна не вказана"
    if l.extra_costs:
        price += f" (+ {l.extra_costs:,.0f} {l.currency})"
    lines = [f"• {l.title} — {price}"]

    details = []
    if l.bedrooms is not None:
        details.append(f"{l.bedrooms} спалень")
    if l.living_area:
        details.append(f"{l.living_area:.0f} м²")
    place = " ".join(x for x in (l.postal_code, l.locality) if x)
    if place:
        details.append(place)
    if details:
        lines.append("  " + ", ".join(details))

    lines.append(f"  {l.url}")
    return "\n".join(lines)


def build_body(listings: Sequence[Listing], page_url: str = "") -> str:
    header = f"Знайдено нових оголошень за вашими критеріями: {len(listings)}\n"
    if page_url:
        header += (
            f"\nПовний список із позначками «переглянуто»:\n{page_url}\n"
        )
    return header + "\n" + "\n\n".join(_format_listing(l) for l in listings)


def build_short_body(listings: Sequence[Listing], page_url: str = "") -> str:
    """
    Короткий текст для email: лише кількість і посилання на дошку — без
    переліку самих оголошень (їх зручніше й гарніше дивитись на дошці, з
    фото). Якщо дошка не увімкнена (немає `page_url`) — повертає повний
    список, як build_body, бо без посилання короткий лист марний.
    """
    if not page_url:
        return build_body(listings, page_url)
    return (
        f"Нових оголошень за вашими критеріями: {len(listings)}.\n\n"
        f"Список із фото та позначками «переглянуто»:\n{page_url}\n"
    )


# --- способи сповіщення -------------------------------------------

class Notifier(ABC):
    @abstractmethod
    def notify(self, listings: Sequence[Listing]) -> None:
        ...


class ConsoleNotifier(Notifier):
    def __init__(self, page_url: str = "") -> None:
        self.page_url = page_url

    def notify(self, listings: Sequence[Listing]) -> None:
        print("\n" + "=" * 60)
        print(build_body(listings, self.page_url))
        print("=" * 60 + "\n")


class EmailNotifier(Notifier):
    def __init__(self, settings: EmailSettings, page_url: str = "") -> None:
        self.s = settings
        self.page_url = page_url

    def notify(self, listings: Sequence[Listing]) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[Агрегатор нерухомості] нових оголошень: {len(listings)}"
        msg["From"] = self.s.from_address
        msg["To"] = ", ".join(self.s.to_addresses)
        msg.set_content(build_short_body(listings, self.page_url))

        if self.s.use_ssl:
            # Одразу зашифроване з'єднання (ukr.net, порт 465).
            server = smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30)

        with server:
            if self.s.use_tls and not self.s.use_ssl:
                server.starttls()  # перехід на шифрування вже після з'єднання (Gmail, порт 587)
            server.login(self.s.username, self.s.password)  # пароль зі змінної середовища / .env
            server.send_message(msg)

        log.info("email надіслано на %s", ", ".join(self.s.to_addresses))


class MultiNotifier(Notifier):
    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self.notifiers = list(notifiers)

    def notify(self, listings: Sequence[Listing]) -> None:
        for n in self.notifiers:
            try:
                n.notify(listings)
            except Exception:
                # Збій одного способу не має ламати інші.
                log.exception("спосіб сповіщення %s не спрацював", type(n).__name__)


def build_notifier(settings: NotificationSettings, page_url: str = "") -> Notifier:
    """Створює потрібний Notifier за налаштуваннями."""
    method = settings.method.lower()
    chosen: list[Notifier] = []
    if method in ("console", "both"):
        chosen.append(ConsoleNotifier(page_url))
    if method in ("email", "both"):
        assert settings.email is not None  # перевірено ще в Config.load()
        chosen.append(EmailNotifier(settings.email, page_url))

    if not chosen:
        raise ValueError(f"Невідомий notifications.method: {settings.method!r}")
    return chosen[0] if len(chosen) == 1 else MultiNotifier(chosen)
