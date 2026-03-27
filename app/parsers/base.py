from __future__ import annotations

from typing import Protocol

from app.parsers.models import ParseContext, ParseOutcome, ParseQuery


class PharmacyParser(Protocol):
    """Единый контракт для конкретного парсера аптеки."""

    pharmacy_code: str

    def healthcheck(self) -> bool:
        """Проверка готовности парсера к работе."""

    def parse_one(self, query: ParseQuery, context: ParseContext) -> ParseOutcome:
        """Парсинг одного запроса и возврат унифицированного результата."""

    def close(self) -> None:
        """Освобождение ресурсов (драйвер, сетевые клиенты и т.п.)."""
