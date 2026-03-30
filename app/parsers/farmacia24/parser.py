from __future__ import annotations

import os
import time
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.parsers.models import ParseContext, ParseItem, ParseOutcome, ParseQuery


class Farmacia24Parser:
    """Парсер для gubernskieapteki.ru (бренд 24 Farmacia)."""

    pharmacy_code = "farmacia24"
    base_url = "https://gubernskieapteki.ru/apteki/"
    default_city = "Красноярск"
    site_origin = "https://gubernskieapteki.ru"

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
        # options.add_argument("--window-size=1400,900")
        # return webdriver.Chrome(options=options)

    def _get_driver(self) -> webdriver.Chrome:
        if self._driver is None:
            self._driver = self._make_driver()
        return self._driver

    def _wait(self, driver: webdriver.Chrome, timeout: int) -> WebDriverWait:
        return WebDriverWait(driver, timeout)

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
        time.sleep(3)

        close_btn = self._wait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".popup__close"))
        )
        driver.execute_script("arguments[0].click();", close_btn)

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
        search_input.click()
        search_input.clear()
        search_input.send_keys(normalized_query)

        self._wait(driver, timeout).until(
            lambda _driver: (
                (_driver.find_element(By.CSS_SELECTOR, ".header-search__input").get_attribute("value") or "").strip()
                == normalized_query
            )
        )

        search_button = self._wait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".header-search__button"))
        )
        driver.execute_script("arguments[0].click();", search_button)
        time.sleep(0.5)

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

    def _extract_first_result(self, driver: webdriver.Chrome) -> ParseItem:
        rows = driver.find_elements(By.CSS_SELECTOR, ".catalog-product-list__row")
        if not rows:
            raise TimeoutException("Search results list is empty")

        first = rows[0]

        title = ""
        title_meta = first.find_elements(By.CSS_SELECTOR, "meta[itemprop='name']")
        if title_meta:
            title = (title_meta[0].get_attribute("content") or "").strip()
        if not title:
            title_spans = first.find_elements(By.CSS_SELECTOR, ".product-card__info-title [aria-label]")
            if title_spans:
                title = (title_spans[0].text or "").strip()

        price = ""
        price_meta = first.find_elements(By.CSS_SELECTOR, ".product-card__price [itemprop='price']")
        if price_meta:
            price = (price_meta[0].get_attribute("content") or price_meta[0].text or "").strip()
        if not price:
            price_fallback = first.find_elements(By.CSS_SELECTOR, ".product-card__discount-price")
            if price_fallback:
                price = (price_fallback[0].text or "").strip()

        href = ""
        url_meta = first.find_elements(By.CSS_SELECTOR, "meta[itemprop='url']")
        if url_meta:
            href = (url_meta[0].get_attribute("content") or "").strip()
        if not href:
            href_links = first.find_elements(By.CSS_SELECTOR, ".product-card__info-title[href]")
            if href_links:
                href = (href_links[0].get_attribute("href") or "").strip()
        if href and href.startswith("/"):
            href = urljoin(self.site_origin, href)

        return ParseItem(
            source_pharmacy=self.pharmacy_code,
            status="matched",
            title=title,
            price=price,
            href=href,
            payload={"result_index": 0},
        )

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
            query_text = (query.name or "").strip() or (query.raw or "").strip()
            self._submit_search_by_name(driver, query_text, timeout)
            search_state = self._wait_search_state(driver, timeout)

            if search_state == "not_found":
                return ParseOutcome(status="not_found", items=[], error="")

            first_item = self._extract_first_result(driver)
            return ParseOutcome(
                status="matched",
                items=[first_item],
                error="",
            )
        except WebDriverException:
            # Драйвер мог упасть на длинной серии запросов — восстанавливаем сессию 1 раз.
            self.close()
            self._is_prepared = False
            try:
                self._ensure_prepared(context)
                driver = self._get_driver()
                timeout = context.timeout or 15
                query_text = (query.name or "").strip() or (query.raw or "").strip()
                self._submit_search_by_name(driver, query_text, timeout)
                search_state = self._wait_search_state(driver, timeout)
                if search_state == "not_found":
                    return ParseOutcome(status="not_found", items=[], error="")
                first_item = self._extract_first_result(driver)
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
