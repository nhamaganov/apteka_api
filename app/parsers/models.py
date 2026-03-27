from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParseQuery:
    """Нормализованный входной запрос для парсера."""

    name: str
    raw: str = ""
    qty: int | None = None
    dosage: str = ""
    manufacturer: str = ""
    barcode: str = ""
    product_code: str = ""


@dataclass(slots=True)
class ParseContext:
    """Контекст выполнения парсинга."""

    job_id: str
    city: str = ""
    timeout: int = 0
    max_retries: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParseItem:
    """Унифицированная запись результата по одной позиции."""

    source_pharmacy: str
    status: str
    title: str = ""
    price: str = ""
    href: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParseOutcome:
    """Результат выполнения parse_one."""

    status: str
    items: list[ParseItem] = field(default_factory=list)
    error: str = ""
