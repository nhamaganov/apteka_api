from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from app.services.apteka_parser import (
    close_modal_if_any,
    human_pause,
    parse_one_query,
    recover_to_home,
    select_city,
    type_like_human,
)


Outcome = str


@dataclass(frozen=True)
class PharmacyMeta:
    code: str
    title: str


class BasePharmacyEngine:
    meta: PharmacyMeta

    def prepare(self, driver, city: str, timeout: int, job_id: Optional[str] = None) -> Dict:
        raise NotImplementedError

    def parse_query(
        self,
        driver,
        query_name: str,
        timeout: int,
        max_retries: int,
        expected_qty: Optional[int] = None,
        expected_dosage: Optional[str] = None,
        qty_is_sum: bool = False,
        raw_input: Optional[str] = None,
        query_manufacturer: str = "",
        job_id: Optional[str] = None,
    ) -> Tuple[Outcome, List[Dict]]:
        raise NotImplementedError


class AptekaRuEngine(BasePharmacyEngine):
    meta = PharmacyMeta(code="apteka_ru", title="Apteka.ru")

    def prepare(self, driver, city: str, timeout: int, job_id: Optional[str] = None) -> Dict:
        recover_to_home(driver)
        close_modal_if_any(driver, timeout=2)
        select_city(driver, city, timeout=timeout)
        return {"selected_city": city}

    def parse_query(
        self,
        driver,
        query_name: str,
        timeout: int,
        max_retries: int,
        expected_qty: Optional[int] = None,
        expected_dosage: Optional[str] = None,
        qty_is_sum: bool = False,
        raw_input: Optional[str] = None,
        query_manufacturer: str = "",
        job_id: Optional[str] = None,
    ) -> Tuple[Outcome, List[Dict]]:
        outcome, items = parse_one_query(
            driver,
            query_name,
            timeout,
            max_retries,
            expected_qty=expected_qty,
            expected_dosage=expected_dosage,
            qty_is_sum=qty_is_sum,
            raw_input=raw_input,
            query_manufacturer=query_manufacturer,
            job_id=job_id,
        )
        for item in items:
            item.setdefault("pharmacy", self.meta.code)
            item.setdefault("pharmacy_title", self.meta.title)
        return outcome, items


class ZdravcityEngine(BasePharmacyEngine):
    meta = PharmacyMeta(code="zdravcity", title="Zdravcity")

    def prepare(self, driver, city: str, timeout: int, job_id: Optional[str] = None) -> Dict:
        city_name = (city or "").strip()
        human_pause()
        driver.get("https://zdravcity.ru/")
        region_input_selector = "input.TextField_text-field-input__FqRfW[placeholder='Название региона']"
        region_label_selector = "div.RegionLabel_label__U9eXf.Info_address-label___9_P3"
        options_selector = "ul.Autocomplete_autocomplete-suggestions__7QhAe div.Autocomplete_region-autocomplete-suggestion__OvNQ1"
        wait = WebDriverWait(driver, timeout)

        try:
            input_element = wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, region_input_selector))
            )
        except TimeoutException:
            input_element = None

        if input_element is None:
            trigger = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, region_label_selector)))
            human_pause()
            trigger.click()
            human_pause()
            input_element = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, region_input_selector)))

        if input_element is None:
            raise TimeoutException("Не удалось открыть выбор региона в Zdravcity")

        human_pause()
        input_element.click()
        human_pause()
        input_element.send_keys(Keys.CONTROL, "a")
        human_pause()
        input_element.send_keys(Keys.BACKSPACE)
        human_pause()
        type_like_human(input_element, city_name)

        end_time = time.time() + timeout
        selected = False
        while time.time() < end_time and not selected:
            for option in driver.find_elements(By.CSS_SELECTOR, options_selector):
                option_text = (option.text or "").strip()
                if option_text == city_name:
                    human_pause()
                    option.click()
                    human_pause()
                    selected = True
                    break
            if not selected:
                time.sleep(0.2)

        if not selected:
            raise TimeoutException(f"Не нашли точное совпадение города '{city_name}' в Zdravcity")

        end_time = time.time() + timeout
        final_city = ""
        while time.time() < end_time:
            try:
                city_span = driver.find_element(By.CSS_SELECTOR, f"{region_label_selector} span")
                final_city = (city_span.text or "").strip()
                if final_city:
                    break
            except Exception:
                pass
            time.sleep(0.2)

        if not final_city:
            final_city = city_name

        return {"selected_city": final_city}

    def parse_query(
        self,
        driver,
        query_name: str,
        timeout: int,
        max_retries: int,
        expected_qty: Optional[int] = None,
        expected_dosage: Optional[str] = None,
        qty_is_sum: bool = False,
        raw_input: Optional[str] = None,
        query_manufacturer: str = "",
        job_id: Optional[str] = None,
    ) -> Tuple[Outcome, List[Dict]]:
        wait = WebDriverWait(driver, timeout)

        for _ in range(max_retries):
            try:
                search_input = wait.until(
                    EC.visibility_of_element_located((By.ID, "headerSearchInput"))
                )
                search_input.click()
                search_input.send_keys(Keys.CONTROL, "a")
                search_input.send_keys(Keys.BACKSPACE)
                search_input.send_keys((query_name or "").strip())

                search_button = wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//button[contains(@class,'Search_search-button') and normalize-space()='Найти']",
                        )
                    )
                )
                search_button.click()

                wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div[class*='ProductsList_list-grid-inner']")
                    )
                )

                first_title = wait.until(
                    EC.visibility_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "div[class*='ProductsList_list-grid-item'] a[class*='Horizontal_horizontal-title'] span[title]",
                        )
                    )
                )
                title_text = (first_title.get_attribute("title") or first_title.text or "").strip()
                if not title_text:
                    time.sleep(0.3)
                    continue
                return "matched", [
                    {
                        "input_name": query_name,
                        "input_qty": expected_qty,
                        "input_dosage": expected_dosage,
                        "title": title_text,
                        "price": "",
                        "link": driver.current_url,
                        "message": "Найден первый результат Zdravcity",
                        "pharmacy": self.meta.code,
                        "pharmacy_title": self.meta.title,
                    }
                ]
            except TimeoutException:
                time.sleep(0.5)

        return "not_found", [
            {
                "input_name": query_name,
                "input_qty": expected_qty,
                "input_dosage": expected_dosage,
                "title": "",
                "price": "",
                "link": driver.current_url,
                "message": "Не удалось получить первый результат Zdravcity",
                "pharmacy": self.meta.code,
                "pharmacy_title": self.meta.title,
            }
        ]


PHARMACY_ENGINES: Dict[str, BasePharmacyEngine] = {
    AptekaRuEngine.meta.code: AptekaRuEngine(),
    ZdravcityEngine.meta.code: ZdravcityEngine(),
}


def get_available_pharmacies() -> List[PharmacyMeta]:
    return [engine.meta for engine in PHARMACY_ENGINES.values()]


def get_engine(code: str) -> BasePharmacyEngine:
    return PHARMACY_ENGINES[code]
