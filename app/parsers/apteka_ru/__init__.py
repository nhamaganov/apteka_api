"""Парсер apteka.ru."""

from app.parsers.apteka_ru.parser import make_driver, recover_to_home, close_modal_if_any, parse_one_query, select_city

__all__ = [
    "make_driver",
    "recover_to_home",
    "close_modal_if_any",
    "parse_one_query",
    "select_city",
]
