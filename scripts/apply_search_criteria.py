#!/usr/bin/env python3
"""
Застосовує нові критерії пошуку до config.yaml зі значень форми GitHub
Actions (вкладка Actions -> Run workflow). Викликається кроком
workflow_dispatch у .github/workflows/check.yml — самостійно запускати
не треба (хоча можна, для перевірки: див. приклад унизу файлу).

Кожне поле читається зі змінної середовища CRITERIA_<НАЗВА>:
    - порожній рядок                     -> поле НЕ чіпаємо;
    - слово "null" (без різниці регістру) -> прибрати обмеження;
    - будь-яке інше значення              -> нове значення поля.

Після запису перевіряє, що розділ search: у config.yaml і далі коректно
розбирається (через aggregator.config.load_search_criteria — саме
розділ search:, без пошти й решти налаштувань, бо їх тут перевіряти не
треба). Якщо ні — повертає файл, яким він був, і завершується з
помилкою, щоб зламаний файл не потрапив у репозиторій.

Приклад ручного запуску (з кореня проєкту):
    $env:CRITERIA_PRICE_MAX = "900"
    python scripts/apply_search_criteria.py
    # або на іншому файлі (напр. для перевірки, щоб не чіпати свій):
    python scripts/apply_search_criteria.py --config C:/tmp/other.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregator.config import load_search_criteria  # noqa: E402
from aggregator.config_editor import (  # noqa: E402
    UNSET,
    CriteriaUpdateError,
    update_search_criteria,
)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

_NO_CHANGE_CHOICE = "(без змін)"


def _raw(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _text_or_unset(name: str):
    value = _raw(name)
    if not value or value == _NO_CHANGE_CHOICE:
        return UNSET
    if value.lower() == "null":
        return None
    return value


def _number_or_unset(name: str, kind):
    value = _raw(name)
    if not value:
        return UNSET
    if value.lower() == "null":
        return None
    try:
        return kind(value)
    except ValueError:
        raise SystemExit(f"{name}: {value!r} — це не число.")


def _list_or_unset(name: str):
    value = _raw(name)
    if not value:
        return UNSET
    if value.lower() == "null":
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _property_types_or_unset():
    value = _raw("CRITERIA_PROPERTY_TYPES")
    if not value or value == _NO_CHANGE_CHOICE:
        return UNSET
    if value.lower() == "null":
        return None
    if value == "house та apartment":
        return ["house", "apartment"]
    return [value]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c", "--config", default=_DEFAULT_CONFIG_PATH, type=Path,
        help="шлях до config.yaml (типово: config.yaml поруч із проєктом)",
    )
    args = parser.parse_args(argv)
    config_path = args.config

    fields = dict(
        transaction=_text_or_unset("CRITERIA_TRANSACTION"),
        property_types=_property_types_or_unset(),
        price_min=_number_or_unset("CRITERIA_PRICE_MIN", float),
        price_max=_number_or_unset("CRITERIA_PRICE_MAX", float),
        bedrooms_min=_number_or_unset("CRITERIA_BEDROOMS_MIN", int),
        bedrooms_max=_number_or_unset("CRITERIA_BEDROOMS_MAX", int),
        living_area_min=_number_or_unset("CRITERIA_LIVING_AREA_MIN", float),
        postal_codes=_list_or_unset("CRITERIA_POSTAL_CODES"),
        localities=_list_or_unset("CRITERIA_LOCALITIES"),
    )

    changed_fields = [name for name, value in fields.items() if value is not UNSET]
    if not changed_fields:
        print("Жодного поля не задано — config.yaml лишається без змін.")
        return 0

    original = config_path.read_text(encoding="utf-8")

    try:
        changed = update_search_criteria(config_path, **fields)
    except CriteriaUpdateError as exc:
        print(f"Не вдалося оновити config.yaml: {exc}", file=sys.stderr)
        return 1

    try:
        load_search_criteria(config_path)
    except Exception as exc:
        config_path.write_text(original, encoding="utf-8")
        print(f"Нові критерії зробили config.yaml невалідним, скасовую зміну: {exc}", file=sys.stderr)
        return 1

    if changed:
        print("Оновлено критерії пошуку:", ", ".join(changed_fields))
    else:
        print("Нові значення співпали з поточними — config.yaml не змінився.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
