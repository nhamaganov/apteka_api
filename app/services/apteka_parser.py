
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
import random
import re
import time
from typing import List, Dict, Optional, Tuple, Literal
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, WebDriverException

from app.utils.match import (
    is_name_match,
    normalize,
    extract_query_manufacturer,
    manufacturer_match_details,
)



Outcome = Literal["matched", "not_found", "failed"]


# ---------------------------
# Wait helpers
# ---------------------------

def w(driver, timeout) -> WebDriverWait:
    """Сокрощение функции WebDriverWait"""
    return WebDriverWait(driver, timeout)


def find(driver_or_el, by, value, timeout) -> w:
    """Сокрощение функции presence_of_element_located"""
    return w(driver_or_el, timeout).until(EC.presence_of_element_located((by, value)))


def find_visible(driver_or_el, by, value, timeout) -> w:
    """Сокрощение функции visibility_of_element_located"""
    return w(driver_or_el, timeout).until(EC.visibility_of_element_located((by, value)))


def find_clickable(driver_or_el, by, value, timeout) -> w:
    """Сокрощение функции element_to_be_clickable"""
    return w(driver_or_el, timeout).until(EC.element_to_be_clickable((by, value)))


# ---------------------------
# Driver
# ---------------------------

def make_driver() -> webdriver.Chrome:
    """Создание дравера браузера"""
    options = Options()
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


# ---------------------------
# Page detectors
# ---------------------------

def is_unexpected_error_page(driver) -> bool:
    """Проверка страницы на ошибку"""
    els = driver.find_elements(By.CSS_SELECTOR, ".UnexpectedError__image")
    return any(el.is_displayed() for el in els)


def is_empty_results_page(driver) -> bool:
    """Проверка"""
    els = driver.find_elements(By.CSS_SELECTOR, ".CardListEmpty")
    return any(el.is_displayed() for el in els)


def is_product_page(driver) -> bool:
    """Возвращает True, если текущая страница похожа на карточку товара."""
    return bool(driver.find_elements(By.CSS_SELECTOR, "h1.ViewProductPage__title"))


def is_search_results_page(driver) -> bool:
    """Возвращает True, если текущая страница похожа на результаты поиска."""
    return bool(driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex"))


def get_first_card_title(driver) -> str:
    """Возвращает заголовок первой карточки результата поиска."""
    cards = driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex")
    if not cards:
        return ""
    try:
        title_el = cards[0].find_element(By.CSS_SELECTOR, "span.catalog-card__name.emphasis")
        return (title_el.get_attribute("title") or title_el.text or "").strip()
    except Exception:
        return ""


# ---------------------------
# UX helpers
# ---------------------------

def backoff_sleep(attempt) -> None:
    """Задает сон в случайном промежутке. Больше с каждой попыткой"""
    base = min(4, 1.5 * (2 ** (attempt - 1)))
    sleep_for = min(4, base + random.uniform(0.2, 0.8))
    time.sleep(sleep_for)


def close_modal_if_any(driver, timeout) -> None:
    """Закрыть модалку, если появилась. Если нет, то не падаем"""
    try:
        close_btn = find_visible(driver, By.CLASS_NAME, "Modal__close", timeout)
        close_btn.click()
    except Exception:
        pass


def select_city(driver, city: str, timeout: int = 8) -> None:
    """Выбирает город в шапке сайта через модалку выбора города."""
    city_name = (city or "").strip()
    if not city_name:
        return

    city_link = find_clickable(
        driver,
        By.CSS_SELECTOR,
        "span.SiteHeaderTop__link.SiteHeaderTop__city",
        timeout,
    )
    city_link.click()
    city_input = find_visible(driver, By.ID, "search-city", timeout)
    city_input.click()
    city_input.send_keys(Keys.CONTROL, "a")
    city_input.send_keys(Keys.BACKSPACE)
    city_input.send_keys(city_name)
    city_name_lower = city_name.lower()

    def matching_city_option(_driver):
        options = _driver.find_elements(By.CSS_SELECTOR, ".TownSelector__options .TownSelector-option")
        for option in options:
            try:
                option_text = (option.text or "").strip()
            except StaleElementReferenceException:
                continue

            if not option_text:
                continue
            if city_name_lower not in option_text.lower():
                continue
            if option.is_displayed() and option.is_enabled():
                return option
        return False

    option = w(driver, timeout).until(matching_city_option)
    option.click()

    w(driver, timeout).until(
        lambda _driver: city_name_lower in (
            (_driver.find_element(By.CSS_SELECTOR, "span.SiteHeaderTop__link.SiteHeaderTop__city").text or "")
            .strip()
            .lower()
        )
    )
    time.sleep(4)


def recover_to_home(driver) -> None:
    """Возвращение на главную страницу"""
    driver.get("https://apteka.ru/")
    
    try:
        close = WebDriverWait(driver, 2).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "Modal__close"))
        )
        close.click()
    
    except Exception:
        pass


def set_search_query(driver, query, timeout) -> None:
    """Заполнение поисковой строку запросом"""
    inp = find_visible(driver, By.ID, "apteka-search", timeout=timeout)
    inp.click()
    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(Keys.BACKSPACE)
    inp.send_keys(normalize(query))


def format_price_2dp(raw: str) -> str:
    """Нормализует сырой текст цены в строку с двумя знаками после запятой."""
    if raw is None:
        return ""
    s = str(raw).replace("\xa0", " ").strip()
    s = s.replace(" ", "")
    s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return ""
    return f"{d:.2f}"


def _price_text_to_amount(raw: str) -> str:
    """Извлекает числовое значение из сырого текста цены."""
    if raw is None:
        return ""
    text = str(raw).replace("\n", " ").replace("\xa0", " ").strip()
    text = re.sub(r"[^\d,.\s]", "", text).strip()
    return format_price_2dp(text)


def _extract_moneyprice_from_content_el(content_el) -> str:
    """
    Извлекает цену из структуры:
    <span class='moneyprice__content'>
      <span class='moneyprice__roubles'>4 559</span>
      <span class='moneyprice__pennies'>.00</span>
    </span>
    """
    try:
        r_els = content_el.find_elements(By.CSS_SELECTOR, ".moneyprice__roubles")
        p_els = content_el.find_elements(By.CSS_SELECTOR, ".moneyprice__pennies")
        r = (r_els[0].text if r_els else "").strip()
        p = (p_els[0].text if p_els else "").strip()
        if r:
            if p and not p.startswith("."):
                p = "." + p
            return _price_text_to_amount(f"{r}{p}")
    except Exception:
        pass
    return _price_text_to_amount(content_el.text or "")


def _has_unavailable_offer(driver) -> bool:
    """Возвращает True, если на странице есть блок 'Нет в наличии'."""
    for el in driver.find_elements(By.CSS_SELECTOR, ".ProductOffer__unavailable"):
        try:
            if el.is_displayed():
                return True
        except Exception:
            continue
    return False


def _get_product_brand(driver) -> str:
    """Возвращает производителя из карточки товара.

    Основной источник: список атрибутов товара (`.ProductAttributesList`) по полю
    с заголовком "Производитель".
    Fallback для старой верстки: `span[itemprop='brand']`.
    """
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, ".ProductAttributesList li dl")
        for row in rows:
            try:
                dt = row.find_element(By.CSS_SELECTOR, "dt")
                if (dt.text or "").strip().lower() != "производитель":
                    continue

                dd = row.find_element(By.CSS_SELECTOR, "dd")
                brand = (dd.text or "").strip()
                if brand:
                    return brand
            except Exception:
                continue

        brand_els = driver.find_elements(By.CSS_SELECTOR, "span[itemprop='brand']")
        if brand_els:
            return (brand_els[0].text or "").strip()
        return ""
    except Exception:
        return ""


def _get_product_dosage(driver) -> Optional[str]:
    """Возвращает дозировку из карточки товара.

    Основной источник: список атрибутов товара (`.ProductAttributesList`) по полю
    с заголовком "Дозировка".
    """
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, ".ProductAttributesList li dl")
        for row in rows:
            try:
                dt = row.find_element(By.CSS_SELECTOR, "dt")
                if (dt.text or "").strip().lower() != "дозировка":
                    continue

                dd = row.find_element(By.CSS_SELECTOR, "dd")
                dosage_raw = (dd.text or "").strip()
                if not dosage_raw:
                    return None
                return normalize_dosage(dosage_raw)
            except Exception:
                continue

        return None
    except Exception:
        return None


def _is_within_unavailable_offer(el) -> bool:
    """Проверяет, что элемент находится внутри блока 'Нет в наличии'."""
    try:
        el.find_element(By.XPATH, "ancestor::*[contains(@class, 'ProductOffer__unavailable')]")
        return True
    except Exception:
        return False


def _extract_variant_qty_from_button(btn) -> Optional[int]:
    """Извлекает количество упаковки из кнопки варианта."""
    try:
        qty_b = btn.find_elements(By.CSS_SELECTOR, ".variantButton__descr em + b")
        if qty_b:
            txt = (qty_b[0].text or "").strip()
            if txt.isdigit():
                return int(txt)
    except Exception:
        pass
    return None


def _get_selected_variant_component_price(driver, expected_qty: Optional[int] = None) -> str:
    """Возвращает цену, показанную в выбранной кнопке варианта."""
    buttons = driver.find_elements(By.CSS_SELECTOR, ".ProductVariants .variantButton")
    if not buttons:
        return ""

    selected = []
    for btn in buttons:
        try:
            selected_flag = btn.get_attribute("aria-selected") == "true"
            qty = _extract_variant_qty_from_button(btn)
            if selected_flag:
                selected.append((btn, qty))
        except Exception:
            continue

    if not selected:
        return ""

    target_btn = None
    if expected_qty is not None:
        for btn, qty in selected:
            if qty == expected_qty:
                target_btn = btn
                break
    if target_btn is None:
        target_btn = selected[0][0]

    try:
        for content_el in target_btn.find_elements(By.CSS_SELECTOR, "span.moneyprice__content"):
            if not content_el.is_displayed():
                continue
            price = _extract_moneyprice_from_content_el(content_el)
            if price:
                return price
    except Exception:
        return ""
    return ""


def _get_sidebar_offer_price(driver) -> str:
    """Возвращает цену из блока предложения в сайдбаре, если есть."""
    if _has_unavailable_offer(driver):
        return ""
    selectors = [
        ".ProductOffer__price span.moneyprice__content",
        ".ProductPanel span.moneyprice__content",
    ]
    for selector in selectors:
        for content_el in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if _is_within_unavailable_offer(content_el):
                    continue
                if not content_el.is_displayed():
                    continue
                price = _extract_moneyprice_from_content_el(content_el)
                if price:
                    return price
            except Exception:
                continue
    return ""


def _get_unavailable_last_price(driver) -> str:
    """Возвращает последнюю цену из блока `Нет в наличии`, если она показана."""
    content_selectors = [
        ".ProductOffer__unavailable .ProductOffer__lastprice span.moneyprice__content",
        ".ProductOffer__lastprice span.moneyprice__content",
    ]
    for selector in content_selectors:
        for content_el in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                price = _extract_moneyprice_from_content_el(content_el)
                if price:
                    return price
            except Exception:
                continue

    # fallback: иногда moneyprice__content может быть скрыт/рендериться иначе,
    # тогда пробуем читать текст контейнера последней цены целиком
    for root in driver.find_elements(By.CSS_SELECTOR, ".ProductOffer__unavailable .ProductOffer__lastprice, .ProductOffer__lastprice"):
        try:
            price = _price_text_to_amount(root.text or "")
            if price:
                return price
        except Exception:
            continue

    return ""


def _is_product_unavailable(driver) -> bool:
    """Возвращает True, если на product page отображается блок недоступности товара."""
    for el in driver.find_elements(By.CSS_SELECTOR, ".ProductOffer__unavailable"):
        try:
            if el.is_displayed():
                return True
        except Exception:
            continue
    return False

def _get_visible_product_page_price(driver, expected_qty: Optional[int] = None) -> str:
    """
    Возвращает цену из видимого блока товара на product page.
    Нужен как основной источник: meta[itemprop='price'] на сайте может
    отставать при переключении вариантов упаковки.
    """
    if _has_unavailable_offer(driver):
        return ""
    variant_component_price = _get_selected_variant_component_price(driver, expected_qty=expected_qty)
    if variant_component_price:
        return variant_component_price

    offer_price = _get_sidebar_offer_price(driver)
    if offer_price:
        return offer_price

    selectors = [
        ".ViewProductPage span.moneyprice__content",
        ".ViewProductPage [class*='moneyprice__content']",
        "span.moneyprice__content",
    ]
    for selector in selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if _is_within_unavailable_offer(el):
                    continue
                if not el.is_displayed():
                    continue
                price = _price_text_to_amount(el.text or "")
                if price:
                    return price
            except StaleElementReferenceException:
                continue
            except Exception:
                continue
    return ""


def _get_meta_product_page_price(driver) -> str:
    """Возвращает цену товара из meta-тега, если он есть."""
    meta = driver.find_elements(By.CSS_SELECTOR, "meta[itemprop='price']")
    if not meta:
        return ""
    val = (meta[0].get_attribute("content") or "").strip()
    return format_price_2dp(val)


def _normalized_product_url(url: str) -> str:
    """Нормализует URL товара для сравнения."""
    s = urlsplit(url)
    path = s.path or "/"
    if not path.endswith("/"):
        path += "/"
    return f"{s.scheme}://{s.netloc}{path}"

# ---------------------------
# Search
# ---------------------------

def run_search_with_retry(driver, query, timeout, max_retries) -> None:
    """Поиск товара с перезагрузкой в случае ошибки"""
    for attempt in range(1, max_retries + 1):
        try:
            prev_first = get_first_card_title(driver)

            set_search_query(driver, query, timeout=timeout)
            find_clickable(driver, By.CSS_SELECTOR, ".SearchBox__input-submit", timeout=timeout).click()

            end = time.time() + timeout
            while time.time() < end:
                if is_unexpected_error_page(driver):
                    raise RuntimeError("UnexpectedError page")
                if is_product_page(driver):
                    return
                if is_empty_results_page(driver):
                    return

                cards = driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex")
                if cards:
                    curr_first = get_first_card_title(driver)

                    # цена в первой карточке
                    price_els = cards[0].find_elements(By.CSS_SELECTOR, "span.moneyprice__content")
                    has_price = bool(price_els and price_els[0].text.strip())

                    # ✅ считаем готово только если первая карточка поменялась (или раньше не было)
                    if has_price and (prev_first == "" or curr_first != prev_first):
                        return

                time.sleep(0.2)
        
            raise TimeoutException("No result within timeout")

        except Exception as e:
            if attempt == max_retries:
                raise RuntimeError(f"Не удалось выполнить поиск '{query}': {e}")
        
            recover_to_home(driver)
            backoff_sleep(attempt)

# ---------------------------
# Parsing
# ---------------------------

@dataclass
class Variant:
    qty: int
    href: str
    selected: bool
    dosage: Optional[str] = None


def normalize_dosage(raw: Optional[str]) -> Optional[str]:
    """Нормализует дозировку к виду `<значение> <единица> [+ ...]` (например, `5 мг + 2 мг`)."""
    if not raw:
        return None

    def _format_number(value: float) -> str:
        return (f"{value:.6f}").rstrip("0").rstrip(".")

    def _normalize_part(value: float, unit: str) -> tuple[float, str]:
        unit = unit.lower()
        # Приводим массовые единицы к единому виду (мг), чтобы
        # `30 мкг` и `0.03 мг` считались одинаковой дозировкой.
        if unit == "мкг":
            return value / 1000, "мг"
        if unit in {"г", "гр"}:
            return value * 1000, "мг"
        return value, unit

    s = str(raw).strip().lower().replace("ё", "е")
    s = re.sub(r"(?<=\d)\s*[\.,]\s*(?=\d)", ".", s)

    def _parentheses_depth(text: str, idx: int) -> int:
        depth = 0
        for pos, ch in enumerate(text):
            if pos >= idx:
                break
            if ch == "(":
                depth += 1
            elif ch == ")" and depth > 0:
                depth -= 1
        return depth

    potency_units = r"ме|мe|me|ед|le|ле|iu"
    matches = list(re.finditer(rf"\b(\d+(?:\.\d+)?)\s*(мкг|мг|г|гр|мл|{potency_units}|%)(?!\w)", s))

    if not matches:
        return None

    min_depth = min(_parentheses_depth(s, m.start()) for m in matches)
    selected_matches = [m for m in matches if _parentheses_depth(s, m.start()) == min_depth]

    parsed_parts: list[tuple[float, str]] = []
    for m in selected_matches:
        raw_value = float(m.group(1))
        value, unit = _normalize_part(raw_value, m.group(2))
        if unit in {"мe", "me", "ед", "le", "ле", "iu"}:
            unit = "ме"
        parsed_parts.append((value, unit))
    if not parsed_parts:
        return None

    parsed_parts = sorted(set(parsed_parts), key=lambda part: (part[1], part[0]))
    parsed_parts.sort(key=lambda part: (part[1], part[0]))
    parts = [f"{_format_number(value)} {unit}" for value, unit in parsed_parts]

    return " + ".join(parts)


def extract_dosage_from_text(text: str) -> Optional[str]:
    """Извлекает дозировку из произвольного текста."""
    return normalize_dosage(text)


def is_dosage_compatible(expected: Optional[str], found: Optional[str]) -> bool:
    """Проверяет, совместимы ли дозировки на уровне компонентов."""
    expected_norm = normalize_dosage(expected)
    found_norm = normalize_dosage(found)

    if expected_norm is None or found_norm is None:
        return False

    if expected_norm == found_norm:
        return True

    expected_parts = set(expected_norm.split(" + "))
    found_parts = set(found_norm.split(" + "))
    if not expected_parts or not found_parts:
        return False

    return bool(expected_parts & found_parts)


def get_variants_from_product_page(driver) -> List[Variant]:
    """
    Возвращает варианты упаковок на странице товара:
    qty (число 'В упаковке'), href (ссылка на этот вариант), selected.
    Если блока вариантов нет — вернёт [].
    """
    variants: List[Variant] = []

    levels = driver.find_elements(By.CSS_SELECTOR, ".ProductVariants__level")
    if levels:
        for level in levels:
            level_dosage = None
            try:
                label_b = level.find_elements(By.CSS_SELECTOR, ".ProductVariants__levelLabel b")
                if label_b:
                    level_dosage = normalize_dosage(label_b[0].text or "")
            except Exception:
                level_dosage = None

            buttons = level.find_elements(By.CSS_SELECTOR, ".variantButton")
            for btn in buttons:
                try:
                    selected = (btn.get_attribute("aria-selected") == "true")

                    qty = None
                    qty_b = btn.find_elements(By.CSS_SELECTOR, ".variantButton__descr em + b")
                    if qty_b:
                        txt = (qty_b[0].text or "").strip()
                        if txt.isdigit():
                            qty = int(txt)

                    if qty is None:
                        descr_text = (btn.text or "")
                        m = re.search(r"В упаковке:\s*(\d+)", descr_text)
                        if m:
                            qty = int(m.group(1))

                    if qty is None:
                        continue

                    link = btn.find_elements(By.CSS_SELECTOR, "a.variantButton__link[href]")
                    if not link:
                        continue
                    href = link[0].get_attribute("href")

                    variants.append(Variant(qty=qty, href=href, selected=selected, dosage=level_dosage))

                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue
    else:
        buttons = driver.find_elements(By.CSS_SELECTOR, ".ProductVariants .variantButton")
        for btn in buttons:
            try:
                selected = (btn.get_attribute("aria-selected") == "true")

                qty = None
                qty_b = btn.find_elements(By.CSS_SELECTOR, ".variantButton__descr em + b")
                if qty_b:
                    txt = (qty_b[0].text or "").strip()
                    if txt.isdigit():
                        qty = int(txt)

                if qty is None:
                    descr_text = (btn.text or "")
                    m = re.search(r"В упаковке:\s*(\d+)", descr_text)
                    if m:
                        qty = int(m.group(1))

                if qty is None:
                    continue

                link = btn.find_elements(By.CSS_SELECTOR, "a.variantButton__link[href]")
                if not link:
                    continue
                href = link[0].get_attribute("href")

                variants.append(Variant(qty=qty, href=href, selected=selected, dosage=None))

            except StaleElementReferenceException:
                continue
            except Exception:
                continue

    return variants


def get_product_page_price(driver, timeout: int = 6, expected_qty: Optional[int] = None) -> str:
    """
    Берём цену в приоритете из видимого блока, затем fallback на meta.
    """
    if _has_unavailable_offer(driver):
        return ""
    end = time.time() + timeout
    while time.time() < end:
        visible_price = _get_visible_product_page_price(driver, expected_qty=expected_qty)
        if visible_price:
            return visible_price

        meta_price = _get_meta_product_page_price(driver)
        if meta_price:
            return meta_price

        last_price = _get_unavailable_last_price(driver)
        if last_price:
            return last_price

        time.sleep(0.2)
    return ""


def extract_pack_qty_from_title(title: str) -> Optional[int]:
    """
    Пытается достать количество (шт) из заголовка товара.
    Примеры:
      - "Белара 21 шт. таблетки..." -> 21
      - "Анжелик N84 ..." -> 84
      - "… 28 шт …" -> 28
    """
    if not title:
        return None
    
    t = title.lower().replace("ё", "е")

    m = re.search(r"\b(\d+)\s*шт\.?\b", t)
    if m:
        return int(m.group(1))

    m = re.search(r"\bn\s*(\d+)\b", t)
    if m:
        return int(m.group(1))
    
    return None


def parse_product_page_one_item(
    driver,
    query_name: str,
    query_raw: str,
    expected_qty: Optional[int],
    expected_dosage: Optional[str],
    qty_is_sum: bool,
    query_manufacturer: str = "",
    query_barcode: str = "",
    timeout: int = 6,
    job_id: str | None = None,
) -> Tuple[bool, Dict]:
    """
    Возвращает (ok, item).
    ok=True -> нашли лучший вариант среди доступных на странице.
    """
    def log_parse(msg: str) -> None:
        if not job_id:
            return
        from app.services.job_runner import job_log
        job_log(job_id, msg)

    normalized_expected_dosage = normalize_dosage(expected_dosage)
    warning_message = "Уточните цену на сайте, возможны неточности" if qty_is_sum else ""

    def build_price_and_message(extra_message: str = "") -> Tuple[str, str]:
        messages: list[str] = []
        if warning_message:
            messages.append(warning_message)
        if extra_message:
            messages.append(extra_message)

        unavailable = _is_product_unavailable(driver)
        unavailable_price = _get_unavailable_last_price(driver) if unavailable else ""
        price = unavailable_price or get_product_page_price(driver, timeout=timeout, expected_qty=expected_qty)
        if unavailable and price:
            messages.append("Нет в наличии, указана последняя цена")

        return price, " | ".join(messages)

    def read_product_title() -> str:
        title_el = find_visible(driver, By.CSS_SELECTOR, "h1.ViewProductPage__title", timeout=timeout)
        return (title_el.text or "").strip()

    def get_current_variant_qty() -> Optional[int]:
        try:
            variants = get_variants_from_product_page(driver)
        except Exception:
            return None

        selected_qty = next((v.qty for v in variants if v.selected), None)
        if selected_qty is not None:
            return selected_qty

        if len(variants) == 1:
            return variants[0].qty

        return None

    min_match_score = 0.7

    def evaluate_title_match(title: str) -> Tuple[bool, float, Optional[int], Optional[str], Optional[str], str]:
        if not title or "набор" in title.lower():
            return False, 0.0, None, None, None, ""

        if not is_name_match(query_name, title):
            return False, 0.0, None, None, None, ""

        found_brand = _get_product_brand(driver)
        manufacturer_details = manufacturer_match_details(
            query_raw=query_raw,
            site_brand=found_brand,
            query_manufacturer=query_manufacturer,
        )
        manufacturer_log_note = (
            "Сравнение производителя: "
            f"вход='{manufacturer_details['query_source']}' "
            f"(норм='{manufacturer_details['query_normalized']}') | "
            f"сайт='{manufacturer_details['site_raw']}' "
            f"(норм='{manufacturer_details['site_normalized']}') | "
            f"score={manufacturer_details['score']} "
            f"threshold={manufacturer_details['threshold']} "
            f"mixed_alphabet={manufacturer_details['mixed_alphabet']} "
            f"matched={manufacturer_details['matched']}"
        )
        manufacturer_note = f"Производитель score={manufacturer_details['score']}"

        log_parse(manufacturer_log_note)
        if not manufacturer_details["matched"]:
            return False, 0.0, None, None, found_brand, manufacturer_note

        found_qty = extract_pack_qty_from_title(title)
        if found_qty is None:
            found_qty = get_current_variant_qty()

        semax_requested = "семакс" in (query_name or "").lower() or "семакс" in (query_raw or "").lower()
        if semax_requested:
            found_dosage = _get_product_dosage(driver)
            if found_dosage is None:
                found_dosage = extract_dosage_from_text(title)
        else:
            found_dosage = extract_dosage_from_text(title)
            if found_dosage is None:
                found_dosage = _get_product_dosage(driver)

        criteria_scores: list[float] = []
        notes: list[str] = []

        if expected_qty is not None:
            if found_qty != expected_qty:
                return False, 0.0, found_qty, found_dosage, found_brand, ""
            criteria_scores.append(1.0)

        if normalized_expected_dosage is not None:
            if found_dosage == normalized_expected_dosage:
                dosage_score = 1.0
                dosage_note = "Совпадение дозировки: да"
            elif is_dosage_compatible(normalized_expected_dosage, found_dosage):
                dosage_score = 0.7
                dosage_note = "Совпадение дозировки: частично"
            elif found_dosage is None:
                dosage_score = 0.4
                dosage_note = "Совпадение дозировки: нет данных"
            else:
                dosage_score = 0.0
                dosage_note = "Совпадение дозировки: нет"
            notes.append(dosage_note)
            criteria_scores.append(dosage_score)

        if not criteria_scores:
            score = 1.0
        else:
            score = sum(criteria_scores) / len(criteria_scores)

        if score < min_match_score:
            return False, 0.0, found_qty, found_dosage, found_brand, ""

        notes.append(manufacturer_note)
        return True, score, found_qty, found_dosage, found_brand, " | ".join(notes)

    def build_item(
        title: str,
        found_qty: Optional[int],
        found_dosage: Optional[str],
        found_brand: Optional[str],
        extra_message: str,
    ) -> Dict:
        price, message = build_price_and_message(extra_message=extra_message)
        return {
            "input_name": query_name,
            "input_manufacturer": query_manufacturer or extract_query_manufacturer(query_raw),
            "input_barcode": query_barcode,
            "title": title,
            "found_manufacturer": found_brand or "",
            "price": price,
            "input_qty": expected_qty,
            "input_dosage": normalized_expected_dosage,
            "found_qty": found_qty,
            "found_dosage": found_dosage,
            "message": message,
        }

    best_score = -1.0
    best_item: Optional[Dict] = None

    def consider_current_page() -> None:
        nonlocal best_score, best_item
        title = read_product_title()
        ok, score, found_qty, found_dosage, found_brand, note = evaluate_title_match(title)
        if not ok:
            return

        if score > best_score:
            best_score = score
            best_item = build_item(title, found_qty, found_dosage, found_brand, note)

    consider_current_page()

    visited_hrefs = {_normalized_product_url(driver.current_url)}
    buttons = driver.find_elements(By.CSS_SELECTOR, ".ProductVariants .variantButton")

    for idx in range(len(buttons)):
        buttons = driver.find_elements(By.CSS_SELECTOR, ".ProductVariants .variantButton")
        if idx >= len(buttons):
            break

        btn = buttons[idx]
        try:
            href_els = btn.find_elements(By.CSS_SELECTOR, "a.variantButton__link[href]")
            href = href_els[0].get_attribute("href") if href_els else ""
            href_norm = _normalized_product_url(href) if href else ""
            if href_norm and href_norm in visited_hrefs:
                continue

            target = href_els[0] if href_els else btn
            old_title = read_product_title()
            old_url = _normalized_product_url(driver.current_url)

            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
            driver.execute_script("arguments[0].click();", target)

            end = time.time() + timeout
            while time.time() < end:
                curr_url = _normalized_product_url(driver.current_url)
                title_nodes = driver.find_elements(By.CSS_SELECTOR, "h1.ViewProductPage__title")
                curr_title = (title_nodes[0].text or "").strip() if title_nodes else ""
                if curr_title and (curr_title != old_title or curr_url != old_url):
                    break
                time.sleep(0.2)

            if href_norm:
                visited_hrefs.add(href_norm)
            visited_hrefs.add(_normalized_product_url(driver.current_url))

            consider_current_page()

        except Exception:
            continue

    if best_item is not None:
        return True, best_item

    not_found_message = "Нет подходящего варианта"
    if warning_message:
        not_found_message = f"{warning_message} | {not_found_message}"

    return False, {
        "input_name": query_name,
        "input_barcode": query_barcode,
        "message": not_found_message,
        "input_qty": expected_qty,
        "input_dosage": normalized_expected_dosage,
    }


def _collect_matching_card_links(driver, query_name: str) -> List[Dict[str, str]]:
    """Собирает ссылки карточек, названия которых подходят по нестрогому совпадению."""
    cards = driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex")
    result: List[Dict[str, str]] = []

    for card in cards:
        try:
            title_el = card.find_element(By.CSS_SELECTOR, "span.catalog-card__name.emphasis")
            title = (title_el.get_attribute("title") or title_el.text or "").strip()
            if not title or "набор" in title.lower():
                continue

            if not is_name_match(query_name, title):
                continue

            href = ""
            link_els = card.find_elements(By.CSS_SELECTOR, "a[href]")
            for link in link_els:
                href_raw = (link.get_attribute("href") or "").strip()
                if not href_raw:
                    continue
                href = href_raw
                break

            if href:
                result.append({"title": title, "href": href})

        except StaleElementReferenceException:
            continue
        except Exception:
            continue

    return result


def parse_cards(
    driver,
    query_name: str,
    query_raw: str,
    expected_qty: Optional[int],
    expected_dosage: Optional[str],
    qty_is_sum: bool,
    timeout: int,
    query_manufacturer: str = "",
    query_barcode: str = "",
    job_id: Optional[str] = None,
) -> List[Dict]:
    """
    В ветке search заходит в каждую подходящую карточку и применяет
    тот же алгоритм, что и parse_product_page_one_item.
    Возвращает первый точный найденный вариант.
    """
    def log_parse(msg: str) -> None:
        if not job_id:
            return
        from app.services.job_runner import job_log
        job_log(job_id, msg)

    search_url = driver.current_url
    candidates = _collect_matching_card_links(driver, query_name)
    log_parse(f"PARSE search candidates={len(candidates)}")

    for idx, candidate in enumerate(candidates, start=1):
        href = candidate["href"]
        title = candidate["title"]
        log_parse(f"PARSE search candidate[{idx}] title={title!r} href={href!r}")

        try:
            driver.get(href)

            if not is_product_page(driver):
                log_parse(f"PARSE search candidate[{idx}] skip: not a product page")
            else:
                ok, item = parse_product_page_one_item(
                    driver,
                    query_name=query_name,
                    query_raw=query_raw,
                    query_manufacturer=query_manufacturer,
                    query_barcode=query_barcode,
                    expected_qty=expected_qty,
                    expected_dosage=expected_dosage,
                    qty_is_sum=qty_is_sum,
                    timeout=timeout,
                    job_id=job_id,
                )
                if ok:
                    log_parse(f"PARSE search candidate[{idx}] matched")
                    return [item]

                log_parse(
                    f"PARSE search candidate[{idx}] not matched: message={item.get('message')!r}"
                )

        except Exception as e:
            log_parse(f"PARSE search candidate[{idx}] failed: {e}")

        # Возвращаемся к поисковой выдаче и продолжаем со следующей карточки.
        driver.get(search_url)
        try:
            find(driver, By.CSS_SELECTOR, ".catalog-card.card-flex", timeout=timeout)
        except Exception:
            pass

    return []

# ---------------------------
# Public API for worker
# ---------------------------

def parse_one_query(
    driver,
    query_name: str,
    timeout,
    max_retries,
    expected_qty: Optional[int] = None,
    expected_dosage: Optional[str] = None,
    qty_is_sum: bool = False,
    raw_input: Optional[str] = None,
    query_manufacturer: str = "",
    query_barcode: str = "",
    job_id: Optional[str] = None,
) -> Tuple[Outcome, List[Dict]]:
    """Парсит один запрос и возвращает результат с найденными позициями."""
    def log_parse(msg: str) -> None:
        """Пишет события парсера в лог текущей задачи."""
        if not job_id:
            return
        from app.services.job_runner import job_log
        job_log(job_id, msg)

    def log_search_result(page_type: str, product_title: str = "", reason: str = "") -> None:
        """Пишет краткий итог поиска в отдельный файл."""
        if not job_id:
            return
        from app.services.job_runner import search_log

        current_url = getattr(driver, "current_url", "")
        parts = [
            f"query_name={query_name!r}",
            f"search_value={search_value!r}",
            f"url={current_url!r}",
            f"page_type={page_type!r}",
        ]
        if product_title:
            parts.append(f"product_title={product_title!r}")
        if reason:
            parts.append(f"reason={reason!r}")
        search_log(job_id, " | ".join(parts))

    search_value = (query_barcode or query_name or "").strip()

    try:
        if expected_dosage is None:
            expected_dosage = extract_dosage_from_text(raw_input or query_name or "")

        run_search_with_retry(driver, search_value, timeout=timeout, max_retries=max_retries)

        page_type = "unknown"
        if is_unexpected_error_page(driver):
            page_type = "unexpected_error"
        elif is_empty_results_page(driver):
            page_type = "empty"
        elif is_product_page(driver):
            page_type = "product"
        elif is_search_results_page(driver):
            page_type = "search"

        log_parse(
            f"PARSE start: query={query_name!r} barcode={query_barcode!r} raw={raw_input!r} query_manufacturer={query_manufacturer!r} expected_qty={expected_qty!r} "
            f"expected_dosage={expected_dosage!r} "
            f"qty_is_sum={qty_is_sum!r} url={driver.current_url!r} page={page_type}"
        )

        if is_empty_results_page(driver):
            log_parse("PARSE context empty results page")
            log_search_result(page_type=page_type, reason="Пустая выдача")
            return "not_found", []
        
        if is_product_page(driver):
            try:
                title_el = driver.find_elements(By.CSS_SELECTOR, "h1.ViewProductPage__title")
                page_title = (title_el[0].text or "").strip() if title_el else ""
            except Exception:
                page_title = ""

            variants = get_variants_from_product_page(driver)
            variants_dump = [
                {"qty": v.qty, "dosage": v.dosage, "selected": v.selected, "href": v.href}
                for v in variants
            ]
            log_parse(
                f"PARSE context product: title={page_title!r} variants={variants_dump!r} "
                f"price_visible={_get_visible_product_page_price(driver)!r} "
                f"price_meta={_get_meta_product_page_price(driver)!r}"
            )

            ok, item = parse_product_page_one_item(
                driver,
                query_name=query_name,
                query_raw=raw_input or query_name,
                query_manufacturer=query_manufacturer,
                query_barcode=query_barcode,
                expected_qty=expected_qty,
                expected_dosage=expected_dosage,
                qty_is_sum=qty_is_sum,
                timeout=timeout,
                job_id=job_id,
            )
            if ok:
                log_search_result(page_type=page_type, product_title=item.get("title", ""))
                return "matched", [item]
            else:
                log_search_result(page_type=page_type, reason=item.get("message", "Не удалось распарсить карточку"))
                return "not_found", [item]

        cards = driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex")
        first_title = get_first_card_title(driver)
        first_price = ""
        if cards:
            try:
                price_els = cards[0].find_elements(By.CSS_SELECTOR, "span.moneyprice__content")
                if price_els:
                    first_price = (price_els[0].text or "").replace("\n", " ").strip()
            except Exception:
                first_price = ""
        log_parse(
            f"PARSE context search: cards={len(cards)} first_title={first_title!r} first_price={first_price!r}"
        )

        items = parse_cards(
            driver,
            query_name=query_name,
            query_raw=raw_input or query_name,
            query_manufacturer=query_manufacturer,
            query_barcode=query_barcode,
            expected_qty=expected_qty,
            expected_dosage=expected_dosage,
            qty_is_sum=qty_is_sum,
            timeout=timeout,
            job_id=job_id,
        )

        if items:
            log_search_result(page_type=page_type, product_title=items[0].get("title", ""))
            return "matched", items

        log_search_result(page_type=page_type, reason="Подходящий товар не найден в выдаче")
        return "not_found", []

    except WebDriverException as e:
        log_search_result(page_type="webdriver_error", reason=str(e))
        return "failed", []
    
    except Exception as e:
        log_search_result(page_type="exception", reason=str(e))
        return "failed", []