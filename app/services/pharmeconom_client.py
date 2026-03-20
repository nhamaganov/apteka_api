import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.settings import PHARMECONOM_COOKIE, PHARMECONOM_TIMEOUT, PHARMECONOM_TOKEN
from app.utils.xls import extract_dosage_from_xls_row, extract_qty_from_xls_row

PRODUCT_INFO_PROPERTY_NAMES = "ID, NAME, PROPERTY_CML2_BAR_CODE, PROPERTY_CML2_MANUFACTURER, PROPERTY_DOSE"


class PharmeconomClientError(RuntimeError):
    """Ошибка при обращении к API pharmeconom."""


class PharmeconomClient:
    """Минимальный клиент для получения информации о товаре по коду."""

    base_url = "https://api.pharmeconom.ru/include/information/product/getInfo.php"

    def __init__(self, token: str | None = None, cookie: str | None = None, timeout: float | None = None):
        self.token = (token or PHARMECONOM_TOKEN).strip()
        self.cookie = (cookie or PHARMECONOM_COOKIE).strip()
        self.timeout = timeout or PHARMECONOM_TIMEOUT

        if not self.token:
            raise PharmeconomClientError("Не задан TOKEN для pharmeconom API")
        if not self.cookie:
            raise PharmeconomClientError("Не задан COOKIE для pharmeconom API")

    def get_product_info(self, product_id: str) -> dict[str, Any]:
        query = urlencode({
            "PROPERTY_NAME": PRODUCT_INFO_PROPERTY_NAMES,
            "XML_ID": product_id,
        })
        request = Request(
            url=f"{self.base_url}?{query}",
            headers={
                "TOKEN": self.token,
                "Cookie": self.cookie,
            },
            method="GET",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PharmeconomClientError(f"Pharmeconom API вернул HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise PharmeconomClientError(f"Не удалось подключиться к pharmeconom API: {exc}") from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PharmeconomClientError("Pharmeconom API вернул некорректный JSON") from exc

        if data.get("status") != "ok":
            raise PharmeconomClientError(f"Pharmeconom API вернул ошибку: {data}")
        return data


def fetch_product_info_rows(client: PharmeconomClient, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Получает product info для строк Excel с кодом товара."""
    items: list[dict[str, Any]] = []

    for row in rows:
        product_code = row["product_code"]
        try:
            api_response = client.get_product_info(product_code)
            items.append({
                **row,
                "status": "ok",
                "api_response": api_response,
                "products": api_response.get("data", []),
            })
        except PharmeconomClientError as exc:
            items.append({
                **row,
                "status": "error",
                "error": str(exc),
                "products": [],
            })

    return items


def build_query_name_from_product_info(name: str) -> str:
    """Нормализует название из Pharmeconom для поискового запроса."""
    query_name = str(name or "").strip()
    if not query_name:
        return ""

    replacements = [
        (r"\b\d+(?:[.,]\d+)?\s*(?:мкг|мг|г|гр|мл|ме|iu|%)(?:\s*\+\s*\d+(?:[.,]\d+)?\s*(?:мкг|мг|г|гр|мл|ме|iu|%))*", " "),
        (r"(?:\bN\s*|№\s*)[\d+]+\b", " "),
        (r"\b\d+\s*шт\.?\b", " "),
        (r"\bтаблетки\s+для\s+рассасывания\b", " "),
        (r"\bкапсулы\b", " "),
        (r"\bкапс\.?\b", " "),
        (r"\bтаблетки\b", " "),
        (r"\bтабл\.?\b", " "),
        (r"\bдраже\b", " "),
        (r"\bпастилки\b", " "),
        (r"\bс\s+коллагеном\b", " "),
        (r"\bмассой\s+\d+(?:[.,]\d+)?\s*(?:мг|г|мл)\b", " "),
        (r"\bвкус\s+[а-яa-z0-9-]+(?:\s+[а-яa-z0-9-]+)*", " "),
    ]

    for pattern, repl in replacements:
        query_name = re.sub(pattern, repl, query_name, flags=re.IGNORECASE)

    query_name = re.sub(r"\s+", " ", query_name).strip(" ,.-")
    return query_name or str(name).strip()


def build_queries_from_product_info(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Собирает поисковые запросы из ответа Get Product Info By Excel."""
    seen: set[tuple[str, Any, str, str]] = set()
    queries: list[dict[str, Any]] = []

    for item in items:
        products = item.get("products") or []
        if not products:
            continue

        for product in products:
            name = str(product.get("NAME") or "").strip()
            if not name:
                continue

            query_name = build_query_name_from_product_info(name)
            if not query_name:
                continue

            dose = str(product.get("PROPERTY_DOSE") or "").strip()
            barcode = str(product.get("PROPERTY_CML2_BAR_CODE") or "").strip()
            qty, qty_is_sum = extract_qty_from_xls_row(name)
            dosage = dose or extract_dosage_from_xls_row(name)
            raw = name

            key = (query_name.lower(), qty, (dosage or "").lower(), barcode)
            if key in seen:
                continue
            seen.add(key)

            queries.append({
                "name": query_name,
                "qty": qty,
                "dosage": dosage,
                "barcode": barcode,
                "qty_is_sum": qty_is_sum,
                "raw": raw,
                "row": raw,
                "product_code": item.get("product_code", ""),
                "row_index": item.get("row_index"),
            })

    return queries