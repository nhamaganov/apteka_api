
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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

from app.core.settings import PARSE_VARIANT_SETTLE_DELAY
from app.utils.match import is_name_match, normalize


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
    # For linux
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,900")
    options.binary_location = "/usr/bin/chromium-browser"
    service = Service("/usr/bin/chromedriver")

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


def has_result(driver) -> bool:
    """Проверка сайта на загрузку данных"""
    if is_empty_results_page(driver):
        return True

    if is_product_page(driver):
        title = driver.find_elements(By.CSS_SELECTOR, "h1.ViewProductPage__title")
        return bool(title and title[0].text.strip())

    cards = driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex")
    if not cards:
        return False
    try:
        price_el = cards[0].find_elements(By.CSS_SELECTOR, "span.moneyprice__content")
        if price_el and price_el[0].text.strip():
            return True
    
    except StaleElementReferenceException:
        return False

    return False

# ---------------------------
# UX helpers
# ---------------------------

def backoff_sleep(attempt) -> None:
    """Задает сон в случайном промежутке. Больше с каждой попыткой"""
    base = min(8, 1.5 * (2 ** (attempt - 1)))
    time.sleep(base + random.uniform(0.2, 0.8))


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
    time.sleep(4)

    city_input = find_visible(driver, By.ID, "search-city", timeout)
    city_input.click()
    city_input.send_keys(Keys.CONTROL, "a")
    city_input.send_keys(Keys.BACKSPACE)
    city_input.send_keys(city_name)
    time.sleep(4)

    first_option = find_clickable(driver, By.CSS_SELECTOR, ".TownSelector__options .TownSelector-option", timeout)
    first_option.click()
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


def _wait_navigation_to_target(driver, target_href: str, timeout: int = 10) -> bool:
    """Ждёт, пока браузер перейдёт по ожидаемому URL."""
    target_norm = _normalized_product_url(target_href)
    end = time.time() + timeout
    while time.time() < end:
        try:
            ready_state = driver.execute_script("return document.readyState")
        except Exception:
            ready_state = ""
        curr_norm = _normalized_product_url(driver.current_url)
        if curr_norm == target_norm and ready_state == "complete":
            return True
        time.sleep(0.2)
    return False

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


def get_variants_from_product_page(driver) -> List[Variant]:
    """
    Возвращает варианты упаковок на странице товара:
    qty (число 'В упаковке'), href (ссылка на этот вариант), selected.
    Если блока вариантов нет — вернёт [].
    """
    variants: List[Variant]  = []

    buttons = driver.find_elements(By.CSS_SELECTOR, ".ProductVariants__level .variantButton")
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

            variants.append(Variant(qty=qty, href=href, selected=selected))
        
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


def get_price_marker(driver) -> str:
    """
    Возвращает маркер состояния product page для ожиданий после
    переключения варианта: selected qty + видимая цена + meta-цена.
    """
    vars_ = get_variants_from_product_page(driver)
    selected_qty = next((str(v.qty) for v in vars_ if v.selected), "")

    visible_price = _get_visible_product_page_price(driver, expected_qty=None)
    meta_price = _get_meta_product_page_price(driver)
    selected_variant_price = _get_selected_variant_component_price(driver, expected_qty=None)
    return f"{selected_qty}|{selected_variant_price}|{visible_price}|{meta_price}"


def wait_price_updated(driver, old_marker: str, timeout: int = 8) -> bool:
    """Ждёт изменения маркера цены товара."""
    end = time.time() + timeout
    while time.time() < end:
        m = get_price_marker(driver)
        if m and m != old_marker:
            return True
        time.sleep(0.2)
    return False


def wait_variant_selected(driver, target_qty: int, timeout: int = 6) -> bool:
    """
    Ждёт, что вариант с target_qty станет выбранным (aria-selected=true).
    """
    end = time.time() + timeout
    while time.time() < end:
        vars_ = get_variants_from_product_page(driver)
        for v in vars_:
            if v.qty == target_qty and v.selected:
                return True

        time.sleep(0.2)
    return False


def select_variant_qty(
    driver,
    target_qty: int,
    timeout: int = 8,
    job_id: str | None = None,
) -> bool:
    """Выбирает вариант упаковки, переходя по его URL."""
    from app.services.job_runner import job_log
    
    variants = get_variants_from_product_page(driver)
    if not variants:
        if job_id:
            job_log(job_id, "VARIANT: no variants found on page")
        return False

    # если нужный вариант уже выбран
    for v in variants:
        if v.qty == target_qty and v.selected:
            if job_id:
                job_log(
                    job_id,
                    f"VARIANT already selected qty={target_qty} "
                    f"url={driver.current_url} "
                    f"price_meta={get_price_marker(driver)!r}"
                )
            return True

    target = next((v for v in variants if v.qty == target_qty), None)
    if not target:
        if job_id:
            job_log(
                job_id,
                f"VARIANT qty={target_qty} not found. "
                f"available={[v.qty for v in variants]}"
            )
        return False

    # ===== ДО ПЕРЕХОДА =====
    old_url = driver.current_url
    old_price = get_price_marker(driver)

    if job_id:
        job_log(
            job_id,
            f"VARIANT switch start qty={target_qty} "
            f"old_url={old_url} "
            f"old_price_meta={old_price!r} "
            f"href={target.href}"
        )

    # ===== ПЕРЕХОД =====
    driver.get(target.href)

    nav_ok = _wait_navigation_to_target(driver, target.href, timeout=max(timeout, 10))
    if job_id:
        job_log(
            job_id,
            f"VARIANT navigation check qty={target_qty} "
            f"target={_normalized_product_url(target.href)!r} "
            f"current={_normalized_product_url(driver.current_url)!r} "
            f"ok={nav_ok}"
        )

    # ждём, что вариант стал selected
    ok_selected = wait_variant_selected(driver, target_qty, timeout)

    # ждём, что цена обновилась
    ok_price = wait_price_updated(driver, old_marker=old_price, timeout=timeout)

    if PARSE_VARIANT_SETTLE_DELAY > 0:
        if job_id:
            job_log(
                job_id,
                f"VARIANT settle delay before reading new price: {PARSE_VARIANT_SETTLE_DELAY:.1f}s"
            )
        time.sleep(PARSE_VARIANT_SETTLE_DELAY)

    # ===== ПОСЛЕ ПЕРЕХОДА =====
    new_url = driver.current_url
    new_price = get_price_marker(driver)
    new_price_component = _get_selected_variant_component_price(driver, expected_qty=target_qty)
    new_price_offer = _get_sidebar_offer_price(driver)

    if job_id:
        job_log(
            job_id,
            f"VARIANT switch end qty={target_qty} "
            f"ok_selected={ok_selected} "
            f"ok_price_change={ok_price} "
            f"new_url={new_url} "
            f"new_price_meta={new_price!r} "
            f"new_price_component={new_price_component!r} "
            f"new_price_offer={new_price_offer!r}"
        )

    return ok_selected


def parse_product_page_one_item(
    driver,
    query_name: str,
    expected_qty: Optional[int],
    qty_is_sum: bool,
    timeout: int = 6,
    job_id: str | None = None,
) -> Tuple[bool, Dict]:
    """
    Возвращает (ok, item).
    ok=True -> нашли нужный вариант (строго 1)
    ok=False -> либо нет подходящего варианта, либо не совпало название
    """
    title_el = find_visible(driver, By.CSS_SELECTOR, "h1.ViewProductPage__title", timeout=timeout)
    title = (title_el.text or "").strip()

    if not title or "набор" in title.lower():
        return False, {"input_name": query_name, "message": "Нет подходящего варианта"}
    
    if not is_name_match(query_name, title):
        return False, {"input_name": query_name, "message": "Нет подходящего варианта"}
    
    warning_message = ""
    if qty_is_sum:
        warning_message = "Уточните цену на сайте, возможны неточности"


    def build_price_and_message() -> Tuple[str, str]:
        """Читает цену и сообщение по текущему состоянию product page."""
        messages: list[str] = []
        if warning_message:
            messages.append(warning_message)

        unavailable = _is_product_unavailable(driver)
        unavailable_price = _get_unavailable_last_price(driver) if unavailable else ""
        price = unavailable_price or get_product_page_price(driver, timeout=timeout, expected_qty=expected_qty)
        if unavailable and price:
            messages.append("Нет в наличии, указана последняя цена")

        message = " | ".join(messages)

        return price, message


    if expected_qty is None:
        price, message = build_price_and_message()
        found_qty = extract_pack_qty_from_title(title)
        return True, {
            "input_name": query_name,
            "title": title,
            "price": price,
            "input_qty": expected_qty,
            "found_qty": found_qty,
            "message": message
        }

    found_qty = extract_pack_qty_from_title(title)
    if found_qty == expected_qty:
        price, message = build_price_and_message()
        return True, {
            "input_name": query_name,
            "title": title,
            "price": price,
            "input_qty": expected_qty,
            "found_qty": found_qty,
            "message": message
        }
    
    if select_variant_qty(driver, expected_qty, timeout=timeout, job_id=job_id):
        title_el = find_visible(driver, By.CSS_SELECTOR, "h1.ViewProductPage__title", timeout=timeout)
        title2 = (title_el.text or "").strip()
        found_qty2 = extract_pack_qty_from_title(title2)
        price2, message2 = build_price_and_message()

        return True, {
            "input_name": query_name,
            "title": title2,
            "price": price2,
            "input_qty": expected_qty,
            "found_qty": found_qty2 if found_qty2 is not None else expected_qty,
            "message": message2
        }

    not_found_message = "Нет подходящего варианта"
    if warning_message:
        not_found_message = f"{warning_message} | {not_found_message}"

    return False, {"input_name": query_name, "message": not_found_message, "input_qty": expected_qty}


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
    expected_qty: Optional[int],
    qty_is_sum: bool,
    timeout: int,
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
                    expected_qty=expected_qty,
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
    qty_is_sum: bool = False,
    raw_input: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Tuple[Outcome, List[Dict]]:
    """Парсит один запрос и возвращает результат с найденными позициями."""
    def log_parse(msg: str) -> None:
        """Пишет события парсера в лог текущей задачи."""
        if not job_id:
            return
        from app.services.job_runner import job_log
        job_log(job_id, msg)

    try:
        run_search_with_retry(driver, query_name, timeout=timeout, max_retries=max_retries)

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
            f"PARSE start: query={query_name!r} raw={raw_input!r} expected_qty={expected_qty!r} "
            f"qty_is_sum={qty_is_sum!r} url={driver.current_url!r} page={page_type}"
        )

        if is_empty_results_page(driver):
            log_parse("PARSE context empty results page")
            return "not_found", []
        
        if is_product_page(driver):
            try:
                title_el = driver.find_elements(By.CSS_SELECTOR, "h1.ViewProductPage__title")
                page_title = (title_el[0].text or "").strip() if title_el else ""
            except Exception:
                page_title = ""

            variants = get_variants_from_product_page(driver)
            variants_dump = [{"qty": v.qty, "selected": v.selected, "href": v.href} for v in variants]
            log_parse(
                f"PARSE context product: title={page_title!r} variants={variants_dump!r} "
                f"price_visible={_get_visible_product_page_price(driver)!r} "
                f"price_meta={_get_meta_product_page_price(driver)!r}"
            )

            ok, item = parse_product_page_one_item(
                driver,
                query_name=query_name,
                expected_qty=expected_qty,
                qty_is_sum=qty_is_sum,
                timeout=timeout,
                job_id=job_id,
            )
            if ok:
                return "matched", [item]
            else:
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
            expected_qty=expected_qty,
            qty_is_sum=qty_is_sum,
            timeout=timeout,
            job_id=job_id,
        )

        if items:
            return "matched", items
        return "not_found", []

    except WebDriverException as e:
        return "failed", []
    
    except Exception:
        return "failed", []
