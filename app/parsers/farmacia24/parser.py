from __future__ import annotations

from app.parsers.models import ParseContext, ParseOutcome, ParseQuery


class Farmacia24Parser:
    """Пустой каркас парсера второй аптеки (24 Farmacia)."""

    pharmacy_code = "farmacia24"

    def healthcheck(self) -> bool:
        """Пока заглушка: парсер доступен как каркас."""
        return True

    def parse_one(self, query: ParseQuery, context: ParseContext) -> ParseOutcome:
        """Пока без реализации: будет заполнено по пошаговой инструкции."""
        _ = (query, context)
        return ParseOutcome(status="not_implemented", items=[], error="Farmacia24 parser is not implemented yet")

    def close(self) -> None:
        """Освобождение ресурсов (пока нечего освобождать)."""
        return None
