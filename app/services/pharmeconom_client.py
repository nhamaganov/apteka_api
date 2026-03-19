import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.settings import PHARMECONOM_COOKIE, PHARMECONOM_TIMEOUT, PHARMECONOM_TOKEN


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
            "PROPERTY_NAME": "ID, NAME, PROPERTY_CML2_BAR_CODE",
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