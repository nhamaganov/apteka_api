from __future__ import annotations

from typing import Callable

from app.parsers.base import PharmacyParser


ParserFactory = Callable[[], PharmacyParser]


class ParserRegistry:
    """Реестр фабрик парсеров по коду аптеки."""

    def __init__(self) -> None:
        self._factories: dict[str, ParserFactory] = {}

    def register(self, pharmacy_code: str, factory: ParserFactory) -> None:
        code = pharmacy_code.strip().lower()
        if not code:
            raise ValueError("pharmacy_code cannot be empty")
        self._factories[code] = factory

    def has(self, pharmacy_code: str) -> bool:
        return pharmacy_code.strip().lower() in self._factories

    def create(self, pharmacy_code: str) -> PharmacyParser:
        code = pharmacy_code.strip().lower()
        if code not in self._factories:
            raise KeyError(f"Parser is not registered for pharmacy '{pharmacy_code}'")
        return self._factories[code]()

    def list_codes(self) -> list[str]:
        return sorted(self._factories)
