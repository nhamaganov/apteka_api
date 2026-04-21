from __future__ import annotations

import os
import random
import re
import time
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.parsers.models import ParseContext, ParseItem, ParseOutcome, ParseQuery
from app.utils.match import is_name_match, manufacturer_match_details, name_match_details
from app.utils.xls import extract_dosage_from_xls_row, extract_qty_from_xls_row
from rapidfuzz import fuzz


class Farmacia24Parser:
    """Парсер для gubernskieapteki.ru (бренд 24 Farmacia)."""

    pharmacy_code = "farmacia24"
    base_url = "https://gubernskieapteki.ru/apteki/"
    default_city = "Красноярск"
    site_origin = "https://gubernskieapteki.ru"
    _QUERY_SERVICE_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\bпокрытые\s+пленочной\s+оболочкой\b", flags=re.IGNORECASE),
        re.compile(r"\bс\s+модифицированным\s+высвобождением\b", flags=re.IGNORECASE),
        re.compile(r"\bмодифицированного\s+высвобождения\b", flags=re.IGNORECASE),
        re.compile(r"\bпролонгированного\s+действия\b", flags=re.IGNORECASE),
        re.compile(r"\bпролонгированного\s+высвобождения\b", flags=re.IGNORECASE),
        re.compile(r"\bдля\s+рассасывания\b", flags=re.IGNORECASE),
        re.compile(r"\bтаб-?депо\b", flags=re.IGNORECASE),
        re.compile(r"\bдвухфазные\b", flags=re.IGNORECASE),
        re.compile(r"\bшипучие\b", flags=re.IGNORECASE),
        re.compile(r"\bжевательные\b", flags=re.IGNORECASE),
        re.compile(r"\bтаблетки\b", flags=re.IGNORECASE),
        re.compile(r"\bтабл\.?\b", flags=re.IGNORECASE),
        re.compile(r"\bтаб\.\b", flags=re.IGNORECASE),
        re.compile(r"\bкапсулы\b", flags=re.IGNORECASE),
        re.compile(r"\bкапс\.?\b", flags=re.IGNORECASE),
        re.compile(r"\bраствор\b", flags=re.IGNORECASE),
        re.compile(r"\bлиофилизат\b", flags=re.IGNORECASE),
        re.compile(r"\bэликсир\b", flags=re.IGNORECASE),
        re.compile(r"\bпастилки\b", flags=re.IGNORECASE),
        re.compile(r"\bгранулы\b", flags=re.IGNORECASE),
        re.compile(r"\bпорошок\b", flags=re.IGNORECASE),
        re.compile(r"\bсуспензия\b", flags=re.IGNORECASE),
        re.compile(r"\bкапли\b", flags=re.IGNORECASE),
        re.compile(r"\bп\.?\s*п/о\b", flags=re.IGNORECASE),
        re.compile(r"\bп/о\b", flags=re.IGNORECASE),
        re.compile(r"\bвн\b", flags=re.IGNORECASE),
    )

    def __init__(self) -> None:
        self._driver: webdriver.Chrome | None = None
        self._is_prepared = False

    def _make_driver(self) -> webdriver.Chrome:
        options = Options()
        headless_enabled = os.environ.get("FARMACIA24_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}
        if headless_enabled:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1400,900")

        chrome_bin = os.environ.get("CHROME_BIN")
        if chrome_bin:
            options.binary_location = chrome_bin

        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
        service = Service(chromedriver_path)
        return webdriver.Chrome(service=service, options=options)

        # For windows
        # options = Options()
        # options.add_argument("--headless=new")
        # options.add_argument("--window-size=1400,900")
        # return webdriver.Chrome(options=options)

    def _get_driver(self) -> webdriver.Chrome:
        if self._driver is None:
            self._driver = self._make_driver()
        return self._driver

    def _wait(self, driver: webdriver.Chrome, timeout: int) -> WebDriverWait:
        return WebDriverWait(driver, timeout)

    def _human_delay(self) -> None:
            """Пауза между действиями, чтобы имитировать поведение пользователя."""
            time.sleep(random.uniform(1.5, 2.5))
    
    def _parse_log(self, job_id: str | None, msg: str) -> None:
        if not job_id:
            return
        from app.services.job_runner import job_log

        job_log(job_id, msg)

    def _open_home(self, driver: webdriver.Chrome, timeout: int) -> None:
        driver.get(self.base_url)
        self._wait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".popup-regions__search-input"))
        )

    def _select_city_in_modal(self, driver: webdriver.Chrome, city_name: str, timeout: int) -> None:
        city_name = (city_name or "").strip() or self.default_city

        city_input = self._wait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".popup-regions__search-input"))
        )

        stale_texts = {
            (item.text or "").strip().lower()
            for item in driver.find_elements(By.CSS_SELECTOR, ".popup-regions__item-text")
            if (item.text or "").strip()
        }

        city_input.click()
        city_input.clear()
        city_input.send_keys(city_name)
        self._human_delay()

        city_name_lower = city_name.lower()

        def city_option_loaded(_driver: webdriver.Chrome):
            option_texts = _driver.find_elements(By.CSS_SELECTOR, ".popup-regions__item-text")
            if not option_texts:
                return False

            normalized = []
            for option in option_texts:
                text = (option.text or "").strip()
                if text:
                    normalized.append(text.lower())

            if not normalized:
                return False

            has_target = any(city_name_lower == txt for txt in normalized)
            is_refreshed = set(normalized) != stale_texts or normalized == [city_name_lower]
            return has_target and is_refreshed

        self._wait(driver, timeout).until(city_option_loaded)

        city_items = driver.find_elements(By.CSS_SELECTOR, ".popup-regions__item")
        target_item = None
        for item in city_items:
            text_els = item.find_elements(By.CSS_SELECTOR, ".popup-regions__item-text")
            if not text_els:
                continue
            if (text_els[0].text or "").strip().lower() == city_name_lower:
                target_item = item
                break

        if target_item is None:
            raise TimeoutException(f"City '{city_name}' not found in regions list")

        driver.execute_script("arguments[0].click();", target_item)

        self._wait(driver, timeout).until_not(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".popup-regions__search-input"))
        )

    def _ensure_city_selected(self, context: ParseContext) -> None:
        driver = self._get_driver()
        timeout = context.timeout or 15
        city_name = self.default_city

        self._open_home(driver, timeout)
        self._select_city_in_modal(driver, city_name, timeout)
        self._scroll_and_close_ad_banner(driver, timeout)
        time.sleep(0.5)
        self._is_prepared = True

    def _ensure_prepared(self, context: ParseContext) -> None:
        if self._is_prepared:
            return
        self._ensure_city_selected(context)

    def _scroll_and_close_ad_banner(self, driver: webdriver.Chrome, timeout: int) -> None:
        """
        После выбора города делаем скролл вниз, ждём появления рекламного баннера
        и закрываем его через кнопку `.popup__close`.
        """
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        close_btn = self._wait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".popup__close"))
        )
        driver.execute_script("arguments[0].click();", close_btn)
        self._human_delay()

        self._wait(driver, timeout).until_not(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".popup__close"))
        )

    def _submit_search_by_name(self, driver: webdriver.Chrome, query_text: str, timeout: int) -> None:
        """
        Заполняет строку поиска `.header-search__input` названием препарата
        и нажимает кнопку поиска `.header-search__button`.
        """
        normalized_query = (query_text or "").strip()
        if not normalized_query:
            raise ValueError("Farmacia24 search query (name) is empty")

        search_input = self._wait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".header-search__input"))
        )
        self._set_search_input_value(driver, search_input, normalized_query, timeout)
        self._human_delay()

        previous_card = self._first_visible_result_card(driver)
        search_button = self._wait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".header-search__button"))
        )
        driver.execute_script("arguments[0].click();", search_button)
        self._wait_loader_to_disappear(driver, timeout)

        if previous_card is not None:
            try:
                self._wait(driver, min(timeout, 5)).until(EC.staleness_of(previous_card))
            except TimeoutException:
                # На сайте иногда переиспользуется DOM-узел карточек. Это не ошибка.
                pass

    def _extract_dropdown_items(self, driver: webdriver.Chrome) -> list[dict]:
        containers = driver.find_elements(By.CSS_SELECTOR, ".header-search__item-container")
        items: list[dict] = []
        for container in containers:
            links = container.find_elements(By.CSS_SELECTOR, ".header-search__item-link")
            for link in links:
                title = (link.text or "").strip()
                if not title:
                    continue
                items.append({"element": link, "title": title})
        return items

    def _score_dropdown_item(self, query: ParseQuery, title: str) -> float:
        name_details = name_match_details(
            query.name,
            title,
            strip_dosage_quantity=True,
        )
        name_score = float(name_details.get("score", 0) or 0)
        if name_score < 50:
            return 0.0

        expected_qty = self._extract_vidora_micro_pack_qty(query.raw or query.name) or query.qty
        found_qty, _ = extract_qty_from_xls_row(title)
        qty_score: float | None = None
        if expected_qty is not None:
            qty_score = 100.0 if found_qty == expected_qty else 0.0
            if qty_score == 0:
                return 0.0

        expected_dosage = extract_dosage_from_xls_row(query.dosage or query.raw or query.name)
        found_dosage = extract_dosage_from_xls_row(title)
        dosage_score: float | None = None
        if expected_dosage:
            if not found_dosage:
                dosage_score = 0.0
            else:
                dosage_score = float(self._dosage_similarity_percent(expected_dosage, found_dosage))
            if dosage_score < 50:
                return 0.0

        weighted_sum = name_score * 0.7
        total_weight = 0.7
        if qty_score is not None:
            weighted_sum += qty_score * 0.15
            total_weight += 0.15
        if dosage_score is not None:
            weighted_sum += dosage_score * 0.15
            total_weight += 0.15
        return weighted_sum / total_weight if total_weight else 0.0

    def _submit_search_via_dropdown(self, driver: webdriver.Chrome, query: ParseQuery, query_text: str, timeout: int) -> tuple[bool, str]:
        normalized_query = re.sub(r"\s+", " ", str(query_text or "")).strip()
        if not normalized_query:
            return False, "пустой поисковый запрос"

        search_input = self._wait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".header-search__input"))
        )
        prefix_query = self._build_dropdown_query_prefix(normalized_query)
        self._set_search_input_value(driver, search_input, prefix_query, timeout, retries=2)

        dropdown_items = self._wait_dropdown_items_or_stable_empty(driver, timeout)
        if not dropdown_items:
            return False, f"dropdown не показал вариантов для запроса {prefix_query!r}"

        best_choice: dict | None = None
        for item in dropdown_items:
            score = self._score_dropdown_item(query, item["title"])
            if score <= 0:
                continue
            if best_choice is None or score > best_choice["score"]:
                best_choice = {
                    "title": item["title"],
                    "score": score,
                }

        if best_choice is None:
            return False, f"варианты dropdown не прошли отбор для запроса {prefix_query!r}"
        if best_choice["score"] < 85:
            return False, f"лучший вариант в dropdown ниже порога: {best_choice['title']!r} (score={best_choice['score']:.1f})"

        refreshed_items = self._extract_dropdown_items(driver)
        for item in refreshed_items:
            if item["title"] == best_choice["title"]:
                driver.execute_script("arguments[0].click();", item["element"])
                self._wait_loader_to_disappear(driver, timeout)
                return True, (
                    f"выбран вариант из dropdown: {best_choice['title']!r} (score={best_choice['score']:.1f}, "
                    f"query={prefix_query!r})"
                )
        return False, f"не удалось найти элемент dropdown для клика: {best_choice['title']!r}"

    def _clear_search_input_hard(self, driver: webdriver.Chrome, search_input, timeout: int) -> None:
        def _input_value() -> str:
            return (driver.find_element(By.CSS_SELECTOR, ".header-search__input").get_attribute("value") or "").strip()

        search_input.click()
        search_input.clear()
        search_input.send_keys(Keys.CONTROL, "a")
        search_input.send_keys(Keys.DELETE)
        search_input.send_keys(Keys.BACKSPACE)

        try:
            self._wait(driver, min(timeout, 2)).until(lambda _driver: _input_value() == "")
            return
        except TimeoutException:
            pass

        driver.execute_script(
            """
            const el = arguments[0];
            el.value = '';
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            search_input,
        )
        self._wait(driver, min(timeout, 2)).until(lambda _driver: _input_value() == "")

    def _set_search_input_value(
        self,
        driver: webdriver.Chrome,
        search_input,
        expected_value: str,
        timeout: int,
        retries: int = 3,
    ) -> None:
        normalized_expected = (expected_value or "").strip()
        last_seen_value = ""
        attempts = max(1, retries)
        for attempt in range(attempts):
            self._clear_search_input_hard(driver, search_input, timeout)
            search_input.send_keys(normalized_expected)
            try:
                self._wait(driver, min(timeout, 3)).until(
                    lambda _driver: (
                        (_driver.find_element(By.CSS_SELECTOR, ".header-search__input").get_attribute("value") or "").strip()
                        == normalized_expected
                    )
                )
                return
            except TimeoutException:
                last_seen_value = (
                    driver.find_element(By.CSS_SELECTOR, ".header-search__input").get_attribute("value") or ""
                ).strip()
                if attempt == attempts - 1:
                    raise TimeoutException(
                        f"search input mismatch after retries: expected={normalized_expected!r}, actual={last_seen_value!r}"
                    )
                continue

    def _wait_dropdown_items_or_stable_empty(self, driver: webdriver.Chrome, timeout: int) -> list[dict]:
        deadline = time.time() + max(1.5, min(float(timeout), 8.0))
        stable_empty_ticks = 0

        while time.time() < deadline:
            items = self._extract_dropdown_items(driver)
            if items:
                return items
            stable_empty_ticks += 1
            if stable_empty_ticks >= 4:
                break
            time.sleep(0.2)

        return []

    def _build_dropdown_query_prefix(self, query_text: str) -> str:
        """
        Для dropdown вводим только префикс запроса:
        - текст до первого служебного слова/фразы (таблетки, капсулы, раствор и т.д.);
        - если служебное слово не найдено, берём половину названия по словам.
        """
        text = re.sub(r"\s+", " ", str(query_text or "")).strip(" ,.;:-")
        if not text:
            return ""

        earliest_start: int | None = None
        for pattern in self._QUERY_SERVICE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            start_idx = match.start()
            if earliest_start is None or start_idx < earliest_start:
                earliest_start = start_idx

        if earliest_start is not None:
            prefix = text[:earliest_start].strip(" ,.;:-")
            if prefix:
                return prefix

        words = [word for word in text.split(" ") if word]
        if not words:
            return text
        half_count = max(1, len(words) // 2)
        return " ".join(words[:half_count]).strip(" ,.;:-")

    def _normalize_query_name_for_search(self, name: str) -> str:
        """
        Нормализует запрос для farmacia24:
        1) удаляет служебные слова;
        2) количество приводит к виду `№N`;
        3) сохраняет полезный текст после количества.
        """
        text = re.sub(r"\s+", " ", str(name or "")).strip()
        if not text:
            return ""

        def _replace_qty(match: re.Match[str]) -> str:
            value = next((group for group in match.groups() if group), "")
            return f" №{value}" if value else " "

        text = re.sub(r"(?i)\b(?:№\s*(\d+)|n\s*(\d+)|(\d+)\s*шт\.?)\b", _replace_qty, text)

        for pattern in self._QUERY_SERVICE_PATTERNS:
            text = pattern.sub(" ", text)

        return re.sub(r"\s+", " ", text).strip(" ,.;:-")
    
    def _wait_loader_to_disappear(self, driver: webdriver.Chrome, timeout: int) -> None:
        """
        После отправки поиска на сайте может появляться оверлей `.loader`.
        Если он появился — ждём, пока полностью исчезнет, прежде чем читать выдачу.
        """
        loader_selector = ".loader"

        try:
            WebDriverWait(driver, min(timeout, 3)).until(
                lambda _driver: any(
                    loader.is_displayed()
                    for loader in _driver.find_elements(By.CSS_SELECTOR, loader_selector)
                )
            )
        except TimeoutException:
            # Лоадер может не появиться на быстрых ответах — это валидный сценарий.
            return

        self._wait(driver, timeout).until(
            lambda _driver: all(
                not loader.is_displayed()
                for loader in _driver.find_elements(By.CSS_SELECTOR, loader_selector)
            )
        )

    def _wait_search_state(self, driver: webdriver.Chrome, timeout: int) -> str:
        """
        Ждёт одно из состояний после поиска:
        - есть результаты `.catalog-product-list__row`
        - пустая выдача `.search-page-not-found`
        """
        def _state(_driver: webdriver.Chrome):
            not_found = _driver.find_elements(By.CSS_SELECTOR, ".search-page-not-found")
            if any(el.is_displayed() for el in not_found):
                return "not_found"

            rows = _driver.find_elements(By.CSS_SELECTOR, ".catalog-product-list__row")
            if any(el.is_displayed() for el in rows):
                return "results"
            return False

        return self._wait(driver, timeout).until(_state)

    def _extract_card_title(self, card) -> str:
        title_meta = card.find_elements(By.CSS_SELECTOR, "meta[itemprop='name']")
        if title_meta:
            return (title_meta[0].get_attribute("content") or "").strip()
        title_spans = card.find_elements(By.CSS_SELECTOR, ".product-card__info-title [aria-label]")
        if title_spans:
            return (title_spans[0].text or "").strip()
        return ""

    def _extract_card_price(self, card) -> str:
        price_meta = card.find_elements(By.CSS_SELECTOR, ".product-card__price [itemprop='price']")
        if price_meta:
            return (price_meta[0].get_attribute("content") or price_meta[0].text or "").strip()
        price_fallback = card.find_elements(By.CSS_SELECTOR, ".product-card__discount-price")
        if price_fallback:
            return (price_fallback[0].text or "").strip()
        return ""

    def _extract_card_href(self, card) -> str:
        url_meta = card.find_elements(By.CSS_SELECTOR, "meta[itemprop='url']")
        href = ""
        if url_meta:
            href = (url_meta[0].get_attribute("content") or "").strip()
        if not href:
            href_links = card.find_elements(By.CSS_SELECTOR, ".product-card__info-title[href]")
            if href_links:
                href = (href_links[0].get_attribute("href") or "").strip()
        if href and href.startswith("/"):
            href = urljoin(self.site_origin, href)
        return href

    def _collect_result_cards(self, driver: webdriver.Chrome) -> list[dict]:
        rows = driver.find_elements(By.CSS_SELECTOR, ".catalog-product-list__row")
        cards_data: list[dict] = []
        card_index = 0
        for row in rows:
            cols = row.find_elements(By.CSS_SELECTOR, ".catalog-product-list__col")
            if not cols:
                cols = [row]
            for col in cols:
                card_wrappers = col.find_elements(By.CSS_SELECTOR, ".product-card.product-card_type_catalog")
                for card in card_wrappers:
                    cards_data.append(
                        {
                            "index": card_index,
                            "title": self._extract_card_title(card),
                            "price": self._extract_card_price(card),
                            "href": self._extract_card_href(card),
                        }
                    )
                    card_index += 1
        return cards_data

    def _first_visible_result_card(self, driver: webdriver.Chrome):
        cards = driver.find_elements(By.CSS_SELECTOR, ".product-card.product-card_type_catalog")
        for card in cards:
            try:
                if card.is_displayed():
                    return card
            except Exception:
                continue
        return None

    def _wait_product_page_loaded(self, driver: webdriver.Chrome, timeout: int) -> None:
        self._wait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".product-page-info__title"))
        )

    def _extract_product_page_title(self, driver: webdriver.Chrome) -> str:
        title_selectors = (
            ".product-page-info__title:not(.seoName)",
            "h1.product-page-info__title:not(.seoName)",
            ".product-page-info__title",
        )
        for selector in title_selectors:
            title_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in title_elements:
                txt = (el.text or "").strip()
                if txt:
                    return txt
        return ""

    def _extract_product_page_price(self, driver: webdriver.Chrome) -> str:
        price_meta = driver.find_elements(By.CSS_SELECTOR, "[itemprop='price']")
        for el in price_meta:
            content = (el.get_attribute("content") or "").strip()
            if content:
                return content
            text = (el.text or "").strip()
            if text:
                return text

        selectors = (
            ".product-page-info__price-current",
            ".product-page-info__price",
            ".product-card__price",
            ".product-card__discount-price",
        )
        for selector in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                text = (el.text or "").strip()
                if text:
                    return text
        return ""

    def _is_product_unavailable(self, driver: webdriver.Chrome) -> bool:
        unavailable_blocks = driver.find_elements(By.CSS_SELECTOR, ".product-page-info.not-available")
        for block in unavailable_blocks:
            try:
                if block.is_displayed():
                    return True
            except Exception:
                continue
        return False

    def _extract_product_page_data(self, driver: webdriver.Chrome, timeout: int) -> tuple[str, str, str]:
        self._wait_product_page_loaded(driver, timeout)
        title = self._extract_product_page_title(driver)
        price = "нет в наличии" if self._is_product_unavailable(driver) else self._extract_product_page_price(driver)

        manufacturer = ""
        manufacturer_els = driver.find_elements(
            By.CSS_SELECTOR, ".product-page-info__property-item-value[itemprop='name']"
        )
        for el in manufacturer_els:
            txt = (el.text or "").strip()
            if txt:
                manufacturer = txt
                break
        return title, manufacturer, price

    def _dosage_similarity_percent(self, expected: str | None, found: str | None) -> int:
        expected_norm = (expected or "").strip().lower()
        found_norm = (found or "").strip().lower()
        if not expected_norm or not found_norm:
            return 0
        if expected_norm == found_norm:
            return 100
        expected_parts = self._parse_dosage_components(expected_norm)
        found_parts = self._parse_dosage_components(found_norm)
        if expected_parts and found_parts:
            unit_scores: list[int] = []
            for unit, expected_values in expected_parts.items():
                found_values = found_parts.get(unit)
                if not found_values:
                    return 0
                unit_scores.append(self._component_values_similarity(expected_values, found_values))
            if unit_scores:
                return min(unit_scores)
        return int(round(fuzz.ratio(expected_norm, found_norm)))

    def _parse_dosage_components(self, dosage_text: str) -> dict[str, list[float]]:
        parts: dict[str, list[float]] = {}
        for number_raw, unit_raw in re.findall(r"(\d+(?:\.\d+)?)\s*(%|мл|мг|ме)", dosage_text):
            try:
                number = float(number_raw)
            except ValueError:
                continue
            unit = unit_raw.lower()
            parts.setdefault(unit, []).append(number)
        for unit in parts:
            parts[unit].sort()
        return parts

    def _component_values_similarity(self, expected_values: list[float], found_values: list[float]) -> int:
        if not expected_values or not found_values:
            return 0
        pair_count = min(len(expected_values), len(found_values))
        ratios: list[float] = []
        for idx in range(pair_count):
            expected = expected_values[idx]
            found = found_values[idx]
            if expected == 0 and found == 0:
                ratios.append(1.0)
                continue
            max_value = max(abs(expected), abs(found))
            if max_value == 0:
                ratios.append(1.0)
                continue
            ratios.append(min(abs(expected), abs(found)) / max_value)
        base_similarity = min(ratios) if ratios else 0.0
        length_penalty = pair_count / max(len(expected_values), len(found_values))
        return int(round(base_similarity * length_penalty * 100))


    def _extract_vidora_micro_pack_qty(self, text: str | None) -> str | None:
        """Для Видора микро сохраняет формат упаковки как `21+7` / `24+4` без суммирования."""
        normalized_text = (text or "").lower().replace("ё", "е")
        if "видора микро" not in normalized_text:
            return None

        match = re.search(
            r"(?:\bN\s*|№\s*)?(\d+)\s*(?:шт\.?)?\s*\+\s*(\d+)\b",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return f"{int(match.group(1))}+{int(match.group(2))}"

    def _is_product_page_match(
        self,
        query: ParseQuery,
        page_title: str,
        page_manufacturer: str,
    ) -> tuple[bool, float, int | str | None, str | None, str | None, str, bool, int | None]:
        found_brand = (page_manufacturer or "").strip()
        name_match = name_match_details(
            query.name,
            page_title,
            strip_dosage_quantity=True,
        )
        compared_query_name = name_match.get("query_normalized", "")
        compared_site_name = name_match.get("site_normalized", "")
        name_score_note = (
            f"Сравнение названий: query={compared_query_name!r}, site={compared_site_name!r} | "
            f"Score названия: {name_match['score']}% "
            f"(token_set={name_match['token_set_score']}%, partial={name_match['partial_score']}%)"
        )
        name_score = float(name_match.get("score", 0) or 0)
        full_name_match = name_score >= 90
        partial_name_match = 50 < name_score < 90
        if not full_name_match and not partial_name_match:
            return (
                False,
                0.0,
                None,
                None,
                found_brand,
                f"название на странице товара не совпало | {name_score_note}",
                False,
                None,
            )
        if partial_name_match:
            name_score_note += " | Частичное совпадение названия (51–89%)"

        expected_vidora_qty = self._extract_vidora_micro_pack_qty(query.raw or query.name)
        found_vidora_qty = self._extract_vidora_micro_pack_qty(page_title)

        found_qty, _ = extract_qty_from_xls_row(page_title)
        expected_qty: int | str | None = query.qty
        if expected_vidora_qty is not None:
            expected_qty = expected_vidora_qty
            found_qty = found_vidora_qty

        qty_score_note = "Score количества: — (в запросе не указано)"
        if expected_qty is not None:
            qty_score = 100 if found_qty == expected_qty else 0
            qty_score_note = (
                f"Score количества: {qty_score}% "
                f"(ожидалось={expected_qty}, найдено={found_qty if found_qty is not None else '—'})"
            )
        if expected_qty is not None and found_qty != expected_qty:
            return (
                False,
                0.0,
                found_qty,
                None,
                found_brand,
                f"кол-во не совпало: ожидалось {expected_qty}, найдено {found_qty} | {name_score_note} | {qty_score_note}",
                False,
                None,
            )

        expected_dosage = extract_dosage_from_xls_row(query.dosage or query.raw or query.name)
        found_dosage = extract_dosage_from_xls_row(page_title)
        dosage_score: float | None = None
        dosage_note = "Score дозировки: — (в запросе не указана)"
        dosage_percent: int | None = None
        if expected_dosage:
            if found_dosage is None:
                dosage_note = f"Score дозировки: — (нет данных, ожидалось {expected_dosage})"
            else:
                dosage_percent = self._dosage_similarity_percent(expected_dosage, found_dosage)
                dosage_score = dosage_percent / 100.0
                dosage_note = (
                    f"Score дозировки: {dosage_percent}% "
                    f"(ожидалось={expected_dosage}, найдено={found_dosage})"
                )
                if dosage_percent < 50:
                    return (
                        False,
                        0.0,
                        found_qty,
                        found_dosage,
                        found_brand,
                        f"дозировка ниже порога 50% | {name_score_note} | {qty_score_note} | {dosage_note}",
                        False,
                        dosage_percent,
                    )

        manufacturer_match = manufacturer_match_details(
            query_raw=query.raw or query.name,
            site_brand=page_manufacturer,
            query_manufacturer=query.manufacturer,
        )
        if manufacturer_match["reason"] == "query_manufacturer_empty":
            manufacturer_score_note = "Score производителя: — (в запросе не указан)"
        else:
            manufacturer_score_note = (
                f"Score производителя: {manufacturer_match['score']}% "
                f"(порог={manufacturer_match['threshold']}%)"
            )
        manufacturer_score = manufacturer_match["score"] if manufacturer_match["reason"] != "query_manufacturer_empty" else 100
        full_manufacturer_match = (
            manufacturer_match["reason"] == "query_manufacturer_empty" or manufacturer_score >= 80
        )
        partial_manufacturer_match = (
            manufacturer_match["reason"] != "query_manufacturer_empty" and 50 <= manufacturer_score < 80
        )
        if manufacturer_match["reason"] != "query_manufacturer_empty" and not partial_manufacturer_match and not full_manufacturer_match:
            return (
                False,
                0.0,
                found_qty,
                found_dosage,
                found_brand,
                f"производитель не совпал | {name_score_note} | {qty_score_note} | {dosage_note} | {manufacturer_score_note}",
                False,
                dosage_percent,
            )

        criteria_scores: list[float] = [name_score / 100.0]
        notes: list[str] = [name_score_note, qty_score_note, dosage_note, manufacturer_score_note]

        if expected_qty is not None:
            criteria_scores.append(1.0)
        if expected_dosage and dosage_score is not None:
            criteria_scores.append(dosage_score)
        if manufacturer_match["reason"] != "query_manufacturer_empty":
            criteria_scores.append(manufacturer_score / 100.0)

        score = sum(criteria_scores) / len(criteria_scores) if criteria_scores else 1.0
        if score < 0.7:
            note = " | ".join([n for n in notes if n]) or "Вариант не прошёл проверку по критериям совпадения"
            return False, 0.0, found_qty, found_dosage, found_brand, note, False, dosage_percent

        perfect_match = (
            (expected_qty is None or found_qty == expected_qty)
            and (
                not expected_dosage
                or dosage_percent is None
                or dosage_percent == 100
            )
            and full_name_match
            and full_manufacturer_match
        )
        note = " | ".join([n for n in notes if n]) or "совпадение найдено"
        return True, score, found_qty, found_dosage, found_brand, note, perfect_match, dosage_percent

    def _find_matching_card(
        self,
        driver: webdriver.Chrome,
        query: ParseQuery,
        timeout: int,
        job_id: str | None = None,
    ) -> tuple[ParseItem | None, str]:
        cards = self._collect_result_cards(driver)
        if not cards:
            return None, "список карточек пуст"

        search_url = driver.current_url
        checked_count = 0
        reasons: list[str] = []
        best_item: ParseItem | None = None
        best_score = -1.0

        prefiltered_cards: list[dict] = []
        expected_vidora_qty = self._extract_vidora_micro_pack_qty(query.raw or query.name)
        expected_qty: int | str | None = expected_vidora_qty or query.qty
        expected_dosage = extract_dosage_from_xls_row(query.dosage or query.raw or query.name)
        for card in cards:
            card_title = (card.get("title") or "").strip()
            if not card_title:
                reasons.append(f"card[{card.get('index')}]: пропущена — пустой заголовок")
                continue
            if is_name_match(
                query.name,
                card_title,
                strip_dosage_quantity=True,
            ):
                found_vidora_qty = self._extract_vidora_micro_pack_qty(card_title)
                found_qty, _ = extract_qty_from_xls_row(card_title)
                if expected_vidora_qty is not None:
                    found_qty = found_vidora_qty
                if expected_qty is not None and found_qty is not None and found_qty != expected_qty:
                    reasons.append(
                        f"card[{card.get('index')}]: отсеяна по количеству в заголовке "
                        f"(ожидалось {expected_qty}, найдено {found_qty}) | title={card_title!r}"
                    )
                    continue

                found_dosage = extract_dosage_from_xls_row(card_title)
                if expected_dosage and found_dosage:
                    dosage_percent = self._dosage_similarity_percent(expected_dosage, found_dosage)
                    if dosage_percent < 50:
                        reasons.append(
                            f"card[{card.get('index')}]: отсеяна по дозировке в заголовке "
                            f"(ожидалось {expected_dosage}, найдено {found_dosage}, score={dosage_percent}%) "
                            f"| title={card_title!r}"
                        )
                        continue
                    
                prefiltered_cards.append(card)

        cards_to_check = prefiltered_cards
        if not cards_to_check:
            reasons.append("предфильтр по названию не сработал, карточки для проверки отсутствуют")
            return None, "; ".join(reasons)

        for card in cards_to_check:
            href = (card.get("href") or "").strip()
            if not href:
                reasons.append(f"card[{card.get('index')}]: отсутствует ссылка на товар")
                continue

            checked_count += 1
            driver.get(href)
            page_title, page_manufacturer, page_price = self._extract_product_page_data(driver, timeout)
            matched, score, found_qty, found_dosage, found_brand, reason, perfect_match, dosage_percent = self._is_product_page_match(
                query, page_title, page_manufacturer
            )
            self._parse_log(
                job_id,
                "FARMACIA24 candidate: "
                f"idx={card.get('index')} matched={matched} perfect={perfect_match} score={score:.3f} "
                f"title={page_title!r} found_qty={found_qty!r} found_dosage={found_dosage!r} "
                f"found_brand={found_brand!r} details={reason!r}",
            )
            if matched:
                name_score_match = re.search(r"Score названия:\s*(\d+(?:[.,]\d+)?)%", reason, flags=re.IGNORECASE)
                candidate_name_score = None
                if name_score_match:
                    try:
                        candidate_name_score = float(name_score_match.group(1).replace(",", "."))
                    except ValueError:
                        candidate_name_score = None
                candidate_partial_name_match = "частичное совпадение названия" in reason.lower()
                candidate_item = ParseItem(
                    source_pharmacy=self.pharmacy_code,
                    status="matched",
                    title=page_title,
                    price=(
                        page_price
                        if page_price == "нет в наличии"
                        else ((card.get("price") or "").strip() or page_price)
                    ),
                    href=driver.current_url,
                    payload={
                        "result_index": card.get("index"),
                        "score": score,
                        "name_score": candidate_name_score,
                        "partial_name_match": candidate_partial_name_match,
                        "found_qty": found_qty,
                        "found_dosage": found_dosage,
                        "found_brand": found_brand,
                        "message": reason,
                        "input_qty": self._extract_vidora_micro_pack_qty(query.raw or query.name) or query.qty,
                        "input_dosage": extract_dosage_from_xls_row(query.dosage or query.raw or query.name),
                        "dosage_similarity_percent": dosage_percent,
                    },
                )
                if perfect_match:
                    return candidate_item, ""
                if score > best_score:
                    best_score = score
                    best_item = candidate_item

            reasons.append(
                f"card[{card.get('index')}]: {reason} | title={page_title!r} | manufacturer={page_manufacturer!r}"
            )

            driver.get(search_url)
            self._wait_search_state(driver, timeout)
        if best_item is not None:
            return best_item, ""
        if checked_count == 0:
            return None, "не удалось открыть ни одной карточки для проверки"
        if reasons:
            return None, "\n".join(reasons[:5])
        return None, "карточки проверены, совпадений не найдено"
    

    def _should_reset_driver(self, exc: WebDriverException) -> bool:
        """
        Перезапускаем браузер только для фатальных проблем с сессией/процессом Chrome.
        Для обычных ошибок ожидания перезапуск не нужен.
        """
        message = (getattr(exc, "msg", "") or str(exc)).lower()
        fatal_markers = (
            "invalid session id",
            "session deleted",
            "disconnected",
            "chrome not reachable",
            "target window already closed",
            "web view not found",
        )
        return any(marker in message for marker in fatal_markers)

    def healthcheck(self) -> bool:
        """Проверка доступности сайта и шага выбора города."""
        try:
            self._ensure_city_selected(ParseContext(job_id="healthcheck", city=self.default_city, timeout=10))
            return True
        except Exception:
            return False

    def parse_one(self, query: ParseQuery, context: ParseContext) -> ParseOutcome:
        """Шаги: выбор города/закрытие баннера → поиск → первая карточка."""
        try:
            self._ensure_prepared(context)
            driver = self._get_driver()
            timeout = context.timeout or 15
            raw_query_text = (query.name or "").strip() or (query.raw or "").strip()
            query_text = self._normalize_query_name_for_search(raw_query_text)
            self._parse_log(
                context.job_id,
                f"FARMACIA24_QUERY_NORMALIZE raw={raw_query_text!r} -> normalized={query_text!r}",
            )
            selected_from_dropdown, dropdown_message = self._submit_search_via_dropdown(
                driver, query, raw_query_text, timeout
            )
            self._parse_log(context.job_id, f"FARMACIA24_DROPDOWN {dropdown_message}")
            if selected_from_dropdown:
                try:
                    self._wait_product_page_loaded(driver, min(timeout, 6))
                    page_title, page_manufacturer, page_price = self._extract_product_page_data(driver, timeout)
                    matched, score, found_qty, found_dosage, found_brand, reason, _, dosage_percent = self._is_product_page_match(
                        query, page_title, page_manufacturer
                    )
                    self._parse_log(
                        context.job_id,
                        "FARMACIA24_DROPDOWN_PAGE_MATCH "
                        f"matched={matched} score={score:.3f} title={page_title!r} reason={reason!r}",
                    )
                    if matched:
                        return ParseOutcome(
                            status="matched",
                            items=[
                                ParseItem(
                                    source_pharmacy=self.pharmacy_code,
                                    status="matched",
                                    title=page_title,
                                    price=page_price,
                                    href=driver.current_url,
                                    payload={
                                        "score": score,
                                        "found_qty": found_qty,
                                        "found_dosage": found_dosage,
                                        "found_brand": found_brand,
                                        "message": reason,
                                        "input_qty": self._extract_vidora_micro_pack_qty(query.raw or query.name) or query.qty,
                                        "input_dosage": extract_dosage_from_xls_row(query.dosage or query.raw or query.name),
                                        "dosage_similarity_percent": dosage_percent,
                                        "selected_via_dropdown": True,
                                    },
                                )
                            ],
                            error="",
                        )
                    self._parse_log(
                        context.job_id,
                        "FARMACIA24_DROPDOWN_FALLBACK mismatch after dropdown click, using standard search flow",
                    )
                except TimeoutException:
                    self._parse_log(
                        context.job_id,
                        "FARMACIA24_DROPDOWN_FALLBACK no product page after dropdown click, using standard search flow",
                    )

            self._submit_search_by_name(driver, query_text, timeout)
            search_state = self._wait_search_state(driver, timeout)

            if search_state == "not_found":
                return ParseOutcome(status="not_found", items=[], error="Поиск на сайте не дал результатов")

            first_item, not_found_reason = self._find_matching_card(driver, query, timeout, context.job_id)
            if first_item is None:
                return ParseOutcome(status="not_found", items=[], error=not_found_reason)
            return ParseOutcome(
                status="matched",
                items=[first_item],
                error="",
            )
        except TimeoutException as exc:
            return ParseOutcome(status="failed", items=[], error=f"Farmacia24 timeout: {exc}")
        except WebDriverException as exc:
            if not self._should_reset_driver(exc):
                return ParseOutcome(status="failed", items=[], error=f"Farmacia24 webdriver error: {exc}")
            # Драйвер мог упасть на длинной серии запросов — восстанавливаем сессию 1 раз.
            self.close()
            self._is_prepared = False
            try:
                self._ensure_prepared(context)
                driver = self._get_driver()
                timeout = context.timeout or 15
                raw_query_text = (query.name or "").strip() or (query.raw or "").strip()
                query_text = self._normalize_query_name_for_search(raw_query_text)
                self._parse_log(
                    context.job_id,
                    f"FARMACIA24_QUERY_NORMALIZE raw={raw_query_text!r} -> normalized={query_text!r}",
                )
                selected_from_dropdown, dropdown_message = self._submit_search_via_dropdown(
                    driver, query, raw_query_text, timeout
                )
                self._parse_log(context.job_id, f"FARMACIA24_DROPDOWN {dropdown_message}")
                if selected_from_dropdown:
                    try:
                        self._wait_product_page_loaded(driver, min(timeout, 6))
                        page_title, page_manufacturer, page_price = self._extract_product_page_data(driver, timeout)
                        matched, score, found_qty, found_dosage, found_brand, reason, _, dosage_percent = self._is_product_page_match(
                            query, page_title, page_manufacturer
                        )
                        self._parse_log(
                            context.job_id,
                            "FARMACIA24_DROPDOWN_PAGE_MATCH "
                            f"matched={matched} score={score:.3f} title={page_title!r} reason={reason!r}",
                        )
                        if matched:
                            return ParseOutcome(
                                status="matched",
                                items=[
                                    ParseItem(
                                        source_pharmacy=self.pharmacy_code,
                                        status="matched",
                                        title=page_title,
                                        price=page_price,
                                        href=driver.current_url,
                                        payload={
                                            "score": score,
                                            "found_qty": found_qty,
                                            "found_dosage": found_dosage,
                                            "found_brand": found_brand,
                                            "message": reason,
                                            "input_qty": self._extract_vidora_micro_pack_qty(query.raw or query.name) or query.qty,
                                            "input_dosage": extract_dosage_from_xls_row(query.dosage or query.raw or query.name),
                                            "dosage_similarity_percent": dosage_percent,
                                            "selected_via_dropdown": True,
                                        },
                                    )
                                ],
                                error="",
                            )
                        self._parse_log(
                            context.job_id,
                            "FARMACIA24_DROPDOWN_FALLBACK mismatch after dropdown click, using standard search flow",
                        )
                    except TimeoutException:
                        self._parse_log(
                            context.job_id,
                            "FARMACIA24_DROPDOWN_FALLBACK no product page after dropdown click, using standard search flow",
                        )

                self._submit_search_by_name(driver, query_text, timeout)
                search_state = self._wait_search_state(driver, timeout)
                if search_state == "not_found":
                    return ParseOutcome(status="not_found", items=[], error="Поиск на сайте не дал результатов")
                first_item, not_found_reason = self._find_matching_card(driver, query, timeout, context.job_id)
                if first_item is None:
                    return ParseOutcome(status="not_found", items=[], error=not_found_reason)
                return ParseOutcome(status="matched", items=[first_item], error="")
            except Exception as exc:
                return ParseOutcome(status="failed", items=[], error=f"Farmacia24 retry failed: {exc}")
        except Exception as exc:
            return ParseOutcome(status="failed", items=[], error=f"Farmacia24 setup/search failed: {exc}")

    def close(self) -> None:
        """Освобождение ресурсов Selenium."""
        if self._driver is not None:
            self._driver.quit()
            self._driver = None
        self._is_prepared = False
