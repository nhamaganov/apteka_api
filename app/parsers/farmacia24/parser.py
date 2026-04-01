from __future__ import annotations

import os
import random
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
from app.utils.match import is_name_match, manufacturer_match_details, name_match_details
from app.utils.xls import extract_dosage_from_xls_row, extract_qty_from_xls_row
from rapidfuzz import fuzz


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
        # options = Options()
        # headless_enabled = os.environ.get("FARMACIA24_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}
        # if headless_enabled:
        #     options.add_argument("--headless=new")
        # options.add_argument("--no-sandbox")
        # options.add_argument("--disable-dev-shm-usage")
        # options.add_argument("--window-size=1400,900")

        # chrome_bin = os.environ.get("CHROME_BIN")
        # if chrome_bin:
        #     options.binary_location = chrome_bin

        # chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
        # service = Service(chromedriver_path)
        # return webdriver.Chrome(service=service, options=options)

        # For windows
        options = Options()
        # options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,900")
        return webdriver.Chrome(options=options)

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
        search_input.click()
        search_input.clear()
        search_input.send_keys(normalized_query)
        self._human_delay()

        self._wait(driver, timeout).until(
            lambda _driver: (
                (_driver.find_element(By.CSS_SELECTOR, ".header-search__input").get_attribute("value") or "").strip()
                == normalized_query
            )
        )

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
            EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.product-page-info__title"))
        )

    def _extract_product_page_data(self, driver: webdriver.Chrome, timeout: int) -> tuple[str, str]:
        self._wait_product_page_loaded(driver, timeout)
        title = (driver.find_element(By.CSS_SELECTOR, "h1.product-page-info__title").text or "").strip()

        manufacturer = ""
        manufacturer_els = driver.find_elements(
            By.CSS_SELECTOR, ".product-page-info__property-item-value[itemprop='name']"
        )
        for el in manufacturer_els:
            txt = (el.text or "").strip()
            if txt:
                manufacturer = txt
                break
        return title, manufacturer

    def _dosage_similarity_percent(self, expected: str | None, found: str | None) -> int:
        expected_norm = (expected or "").strip().lower()
        found_norm = (found or "").strip().lower()
        if not expected_norm or not found_norm:
            return 0
        if expected_norm == found_norm:
            return 100
        if expected_norm in found_norm or found_norm in expected_norm:
            return 100
        return int(round(fuzz.ratio(expected_norm, found_norm)))

    def _is_product_page_match(
        self,
        query: ParseQuery,
        page_title: str,
        page_manufacturer: str,
    ) -> tuple[bool, float, int | None, str | None, str | None, str, bool, int | None]:
        found_brand = (page_manufacturer or "").strip()
        name_match = name_match_details(query.name, page_title)
        name_score_note = (
            f"Score названия: {name_match['score']}% "
            f"(token_set={name_match['token_set_score']}%, partial={name_match['partial_score']}%)"
        )
        if not name_match["matched"]:
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

        found_qty, _ = extract_qty_from_xls_row(page_title)
        expected_qty = query.qty
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
        if manufacturer_match["reason"] != "query_manufacturer_empty" and not manufacturer_match["matched"]:
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

        criteria_scores: list[float] = []
        notes: list[str] = [name_score_note, qty_score_note, dosage_note, manufacturer_score_note]

        if expected_qty is not None:
            criteria_scores.append(1.0)
        if expected_dosage and dosage_score is not None:
            criteria_scores.append(dosage_score)
        if manufacturer_match["reason"] != "query_manufacturer_empty":
            criteria_scores.append(manufacturer_match["score"] / 100.0)

        score = sum(criteria_scores) / len(criteria_scores) if criteria_scores else 1.0
        if score < 0.7:
            note = " | ".join([n for n in notes if n]) or "Вариант не прошёл проверку по критериям совпадения"
            return False, 0.0, found_qty, found_dosage, found_brand, note, False, dosage_percent

        perfect_match = (
            (expected_qty is None or found_qty == expected_qty)
            and (
                not expected_dosage
                or dosage_percent is None
                or dosage_percent > 90
            )
            and (
                manufacturer_match["reason"] == "query_manufacturer_empty"
                or manufacturer_match["matched"]
            )
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
        for card in cards:
            card_title = (card.get("title") or "").strip()
            if not card_title or is_name_match(query.name, card_title):
                prefiltered_cards.append(card)

        cards_to_check = prefiltered_cards if prefiltered_cards else cards
        if not prefiltered_cards:
            reasons.append("предфильтр по названию не сработал, проверяем карточки без фильтра")

        for card in cards_to_check:
            href = (card.get("href") or "").strip()
            if not href:
                reasons.append(f"card[{card.get('index')}]: отсутствует ссылка на товар")
                continue

            checked_count += 1
            driver.get(href)
            page_title, page_manufacturer = self._extract_product_page_data(driver, timeout)
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
                candidate_item = ParseItem(
                    source_pharmacy=self.pharmacy_code,
                    status="matched",
                    title=page_title,
                    price=(card.get("price") or "").strip(),
                    href=driver.current_url,
                    payload={
                        "result_index": card.get("index"),
                        "score": score,
                        "found_qty": found_qty,
                        "found_dosage": found_dosage,
                        "found_brand": found_brand,
                        "message": reason,
                        "input_qty": query.qty,
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
            query_text = (query.name or "").strip() or (query.raw or "").strip()
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
                query_text = (query.name or "").strip() or (query.raw or "").strip()
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
