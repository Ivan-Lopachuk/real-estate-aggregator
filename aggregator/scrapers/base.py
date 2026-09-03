"""
Спільний фундамент для всіх scraper'ів.

`BaseScraper` — абстрактний базовий клас. Він:
    * створює HTTP-сесію з правильними заголовками (User-Agent тощо);
    * зберігає критерії пошуку та мережеві налаштування;
    * зобов'язує кожен дочірній клас реалізувати метод `fetch()`,
      який повертає оголошення у вигляді об'єктів Listing.

Плюс маленький «реєстр»: декоратор @register записує scraper за його
`site_name`, а `get_scraper("immoweb")` дістає потрібний клас. Завдяки
цьому runner.py працює з будь-яким сайтом, не знаючи про нього наперед.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Iterator

import requests

from ..config import HttpSettings, SearchCriteria
from ..models import Listing

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type["BaseScraper"]] = {}


def register(cls: type["BaseScraper"]) -> type["BaseScraper"]:
    """Декоратор класу: додає scraper до реєстру за його site_name."""
    if not getattr(cls, "site_name", ""):
        raise ValueError(f"{cls.__name__}: не задано атрибут site_name")
    _REGISTRY[cls.site_name] = cls
    return cls


def get_scraper(name: str) -> type["BaseScraper"]:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(жодного)"
        raise KeyError(f"Немає scraper'а з назвою {name!r}. Доступні: {known}")


def available_scrapers() -> list[str]:
    return sorted(_REGISTRY)


class BaseScraper(ABC):
    #: Унікальна назва сайту. Саме її пишуть у config.yaml -> sites.
    site_name: str = ""

    def __init__(self, criteria: SearchCriteria, http: HttpSettings) -> None:
        self.criteria = criteria
        self.http = http
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": http.user_agent,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    @abstractmethod
    def fetch(self) -> Iterator[Listing]:
        """Отримати оголошення із сайту за self.criteria."""
        raise NotImplementedError

    # -- дрібні помічники для дочірніх класів --

    def _sleep(self) -> None:
        """Ввічлива пауза між запитами сторінок."""
        if self.http.request_delay_seconds > 0:
            time.sleep(self.http.request_delay_seconds)

    @staticmethod
    def _dig(data, *path):
        """
        Безпечно дістати вкладене значення зі словника (і, за потреби,
        списку — ціле число в path означає «елемент за цим індексом»).
        _dig(d, "a", "b", 0) == d["a"]["b"][0], але повертає None, якщо
        десь на шляху ключа/індексу немає (щоб scraper не падав).
        """
        cur = data
        for key in path:
            if isinstance(cur, dict):
                cur = cur.get(key)
            elif isinstance(cur, list) and isinstance(key, int) and -len(cur) <= key < len(cur):
                cur = cur[key]
            else:
                return None
        return cur
