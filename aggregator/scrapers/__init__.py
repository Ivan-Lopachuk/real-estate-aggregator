"""
Пакет scraper'ів (по одному модулю на сайт).

Просто імпортуючи цей пакет, ви «реєструєте» всі доступні scraper'и:
кожен модуль нижче містить клас із декоратором @register, який додає
його до внутрішнього реєстру. Щоб додати новий сайт — створіть файл
на кшталт immoweb.py і допишіть один рядок import сюди.
"""

from .base import BaseScraper, available_scrapers, get_scraper, register  # noqa: F401
from . import immoweb  # noqa: F401  (import заради реєстрації ImmowebScraper)
from . import immovlan  # noqa: F401  (import заради реєстрації ImmovlanScraper)

__all__ = ["BaseScraper", "available_scrapers", "get_scraper", "register"]
