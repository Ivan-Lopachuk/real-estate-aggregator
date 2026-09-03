"""
Точкове редагування розділу `search:` у config.yaml — так, щоб решта
файлу (коментарі, інші розділи, форматування) лишалась без змін.

Чому не просто перезаписати весь файл через PyYAML: якщо прочитати
config.yaml і записати його назад бібліотекою `yaml`, усі коментарі
зникнуть — а саме вони роблять файл зрозумілим без знання Python. Тому
тут — точкова заміна лише потрібних рядків звичайним пошуком по тексту,
без повного перерозбору файлу.

Хто цим користується:
    * `scripts/apply_search_criteria.py` — викликається кроком GitHub
      Actions, коли ви тиснете Actions -> Run workflow і заповнюєте
      форму з новими критеріями;
    * у майбутньому цю саму функцію зможе викликати й Telegram-бот.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# Позначає «це поле НЕ передали — лишити як є в файлі». На відміну від
# None (Python), який тут означає «прибрати обмеження» (null / []).
UNSET = object()


class CriteriaUpdateError(Exception):
    """Кидається, коли очікуваного рядка/розділу в config.yaml не знайдено."""


def _render_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _replace_scalar(text: str, key: str, value) -> str:
    pattern = re.compile(rf"^(  {re.escape(key)}:).*$", re.MULTILINE)
    new_text, count = pattern.subn(lambda m: f"{m.group(1)} {_render_scalar(value)}", text, count=1)
    if count == 0:
        raise CriteriaUpdateError(f"у config.yaml не знайдено рядок '{key}:' у розділі search")
    return new_text


def _replace_list(text: str, key: str, items: Optional[list[str]], quote: bool) -> str:
    # Захоплює саму адресу "  key: ..." і всі рядки-елементи одразу під
    # нею (відступ 4 пробіли, починаються з "- "), аж до першого рядка,
    # що вже не є елементом списку.
    pattern = re.compile(rf"^  {re.escape(key)}:.*(?:\n    -.*)*\n?", re.MULTILINE)

    if not items:
        replacement = f"  {key}: []\n"
    else:
        fmt = (lambda v: f'    - "{v}"') if quote else (lambda v: f"    - {v}")
        replacement = f"  {key}:\n" + "\n".join(fmt(v) for v in items) + "\n"

    new_text, count = pattern.subn(lambda _m: replacement, text, count=1)
    if count == 0:
        raise CriteriaUpdateError(f"у config.yaml не знайдено розділ '{key}:' у search")
    return new_text


def update_search_criteria(
    path: "str | Path",
    *,
    transaction=UNSET,
    property_types=UNSET,
    price_min=UNSET,
    price_max=UNSET,
    bedrooms_min=UNSET,
    bedrooms_max=UNSET,
    living_area_min=UNSET,
    postal_codes=UNSET,
    localities=UNSET,
) -> bool:
    """
    Змінює в config.yaml лише ті поля розділу search:, які передали
    (не UNSET). Значення None означає «прибрати обмеження» (записується
    як null або порожній список). Повертає True, якщо файл змінився.
    """
    path = Path(path)
    original = path.read_text(encoding="utf-8")
    text = original

    if transaction is not UNSET:
        text = _replace_scalar(text, "transaction", transaction)
    if property_types is not UNSET:
        text = _replace_list(text, "property_types", property_types, quote=False)
    if price_min is not UNSET:
        text = _replace_scalar(text, "price_min", price_min)
    if price_max is not UNSET:
        text = _replace_scalar(text, "price_max", price_max)
    if bedrooms_min is not UNSET:
        text = _replace_scalar(text, "bedrooms_min", bedrooms_min)
    if bedrooms_max is not UNSET:
        text = _replace_scalar(text, "bedrooms_max", bedrooms_max)
    if living_area_min is not UNSET:
        text = _replace_scalar(text, "living_area_min", living_area_min)
    if postal_codes is not UNSET:
        text = _replace_list(text, "postal_codes", postal_codes, quote=True)
    if localities is not UNSET:
        text = _replace_list(text, "localities", localities, quote=True)

    if text == original:
        return False

    path.write_text(text, encoding="utf-8")
    return True
