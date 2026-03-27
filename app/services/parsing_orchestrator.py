from __future__ import annotations

from dataclasses import dataclass

from app.parsers.registry import ParserRegistry


@dataclass(slots=True)
class OrchestratorResult:
    """Результат оркестрации по выбранным аптекам."""

    pharmacy_codes: list[str]


class ParsingOrchestrator:
    """Подготовка к fan-out парсинга по выбранным аптекам."""

    def __init__(self, registry: ParserRegistry) -> None:
        self.registry = registry

    def validate_selection(self, pharmacy_codes: list[str]) -> OrchestratorResult:
        normalized: list[str] = []
        for code in pharmacy_codes:
            normalized_code = code.strip().lower()
            if not normalized_code:
                continue
            if not self.registry.has(normalized_code):
                raise KeyError(f"Unknown pharmacy code: {code}")
            normalized.append(normalized_code)

        if not normalized:
            raise ValueError("At least one pharmacy should be selected")

        return OrchestratorResult(pharmacy_codes=normalized)