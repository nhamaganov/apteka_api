
import random
import time
from typing import List, Dict, Tuple, Literal

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, WebDriverException

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
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,900")
    options.binary_location = "/usr/bin/chromium-browser"
    service = Service("/usr/bin/chromedriver")

    return webdriver.Chrome(service=service, options=options)

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
    return bool(driver.find_elements(By.CSS_SELECTOR, "h1.ViewProductPage__title"))


def is_search_results_page(driver) -> bool:
    return bool(driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex"))


def get_first_card_title(driver) -> str:
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

def parse_product_page(driver, query, timeout) -> List[Dict]:
    title_el = find_visible(driver, By.CSS_SELECTOR, "h1.ViewProductPage__title", timeout=timeout)
    title = (title_el.text or "").strip()
    
    if not title or "набор" in title.lower():
        return []

    price = ""
    price_els = driver.find_elements(By.CSS_SELECTOR, "span.moneyprice__content")
    if price_els:
        price = price_els[0].text.replace("\n", "").replace(" ", "").strip()


    if not is_name_match(query, title):
        return []

    return [{"input_name": query, "title": title, "price": str(price)}]


def parse_cards(driver, query) -> List[Dict]:
    """Парсинг карточек на текущей странице"""
    cards = driver.find_elements(By.CSS_SELECTOR, ".catalog-card.card-flex")
    items = []
    
    for card in cards:
        try:
            title_el = card.find_element(By.CSS_SELECTOR, "span.catalog-card__name.emphasis")
            title = title_el.get_attribute("title") or title_el.text.strip()
            if not title or "набор" in title.lower():
                continue

            if not is_name_match(query,title):
                continue

            price = ""
            price_els = card.find_elements(By.CSS_SELECTOR, "span.moneyprice__content")
            if price_els:
                price = price_els[0].text.replace("\n", "").replace(" ", "").strip()
            
            items.append({"input_name": query, "title": title, "price": str(price)})
        
        except StaleElementReferenceException:
            continue
        except Exception:
            continue
    
    return items

# ---------------------------
# Public API for worker
# ---------------------------

def parse_one_query(driver, query, timeout, max_retries) -> Tuple[Outcome, List[Dict]]:
    try:
        run_search_with_retry(driver, query, timeout=timeout, max_retries=max_retries)

        if is_empty_results_page(driver):
            return "not_found", []
        
        if is_product_page(driver):
            items = parse_product_page(driver, query=query, timeout=timeout)
        else:
            items = parse_cards(driver,query=query)
        
        if items:
            return "matched", items

        return "not_found", []

    except WebDriverException as e:
        return "failed", []
    
    except Exception:
        return "failed", []