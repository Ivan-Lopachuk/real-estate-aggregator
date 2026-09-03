#!/usr/bin/env python3
"""
Точка входу програми — файл, який ви запускаєте.

Приклади:
    python main.py                 # один прохід і вихід
    python main.py --loop          # працювати постійно, перевіряти за розкладом
    python main.py -c my.yaml      # інший файл налаштувань
    python main.py -v              # докладний (debug) журнал
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from aggregator.config import Config, ConfigError

# Імпорт пакета scrapers реєструє всі доступні scraper'и (immoweb тощо).
import aggregator.scrapers  # noqa: F401
from aggregator.runner import run_forever, run_once


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Пошук нерухомості на сайтах і сповіщення про нові оголошення."
    )
    p.add_argument(
        "-c", "--config", default="config.yaml", type=Path,
        help="шлях до файлу налаштувань (типово: config.yaml)",
    )
    p.add_argument(
        "--loop", action="store_true",
        help="працювати постійно, перевіряючи за інтервалом із config.yaml",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="докладний журнал (рівень DEBUG)",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # Змусити вивід працювати в UTF-8 навіть поза терміналом (напр. під
    # Планувальником завдань Windows), інакше кирилиця в тексті оголошень
    # спричиняє UnicodeEncodeError і програма падає.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = Config.load(args.config)
    except (ConfigError, FileNotFoundError) as exc:
        print(f"Проблема з налаштуваннями: {exc}", file=sys.stderr)
        return 2

    if args.loop:
        try:
            run_forever(config)
        except KeyboardInterrupt:
            print("\nЗупинено користувачем.")
        return 0

    new_count = run_once(config)
    print(f"Готово. Нових оголошень: {new_count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
