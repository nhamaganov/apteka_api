from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from app.services.apteka_parser import (
    close_modal_if_any,
    parse_one_query,
    recover_to_home,
    select_city,
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
        driver.get("https://zdravcity.ru/")
        region_input_selector = "input.TextField_text-field-input__FqRfW[placeholder='Название региона']"
        region_label_selector = "div.RegionLabel_label__U9eXf.Info_address-label___9_P3"
        options_selector = "ul.Autocomplete_autocomplete-suggestions__7QhAe div.Autocomplete_region-autocomplete-suggestion__OvNQ1"
        input_element = None
        try:
            input_element = driver.find_element(By.CSS_SELECTOR, region_input_selector)
            time.sleep(3)
            if not input_element.is_displayed():
                input_element = None
        except Exception:
            input_element = None

        if input_element is None:
            trigger = driver.find_element(By.CSS_SELECTOR, region_label_selector)
            trigger.click()
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    input_element = driver.find_element(By.CSS_SELECTOR, region_input_selector)
                    if input_element.is_displayed():
                        break
                except Exception:
                    pass
                time.sleep(0.2)

        if input_element is None:
            raise TimeoutException("Не удалось открыть выбор региона в Zdravcity")

        input_element.click()
        input_element.send_keys(Keys.CONTROL, "a")
        input_element.send_keys(Keys.BACKSPACE)
        input_element.send_keys(city_name)

        end_time = time.time() + timeout
        selected = False
        while time.time() < end_time and not selected:
            for option in driver.find_elements(By.CSS_SELECTOR, options_selector):
                option_text = (option.text or "").strip()
                if option_text == city_name:
                    option.click()
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
        return "not_found", [
            {
                "input_name": query_name,
                "title": "",
                "price": "",
                "link": driver.current_url,
                "message": "Для Zdravcity пока реализован только выбор города",
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
