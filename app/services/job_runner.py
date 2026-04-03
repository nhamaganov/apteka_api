import asyncio
import time
from datetime import datetime
from typing import Dict, List
from zoneinfo import ZoneInfo

from app.core.settings import PARSE_MAX_RETRIES, PARSE_PAUSE, PARSE_TIMEOUT
from app.core.storage import farmacia24_log_path, log_path, normalization_log_path, result_file_path, search_log_path, status_path, result_path, queries_path, read_json, write_json, upload_path
from app.core.queue import JobQueue
from app.core.time import now_iso
from app.parsers.farmacia24.parser import Farmacia24Parser
from app.parsers.models import ParseContext, ParseQuery
from app.utils.match import extract_query_manufacturer
from app.utils.xls import build_enriched_xlsx, build_flat_xlsx
from app.parsers.apteka_ru.parser import make_driver, recover_to_home, close_modal_if_any, parse_one_query, select_city


async def process_job(job_id: str) -> None:
    """Запускает полный цикл парсинга для одной задачи в отдельном потоке."""
    await asyncio.to_thread(_process_job_sync, job_id)


def _process_job_sync(job_id: str) -> None:
    """Запускает полный цикл парсинга для одной задачи."""
    status = read_json(status_path(job_id))
    status["status"] = "running"
    status["started_at"] = now_iso()
    status["finished_at"] = None
    status["error"] = None
    write_json(status_path(job_id), status)

    queries_data = read_json(queries_path(job_id))
    queries = queries_data.get("queries", [])
    selected_city = queries_data.get("city", "")
    pharmacy_codes = queries_data.get("pharmacy_codes", ["apteka_ru"])
    pharmacy_codes = [str(code).strip().lower() for code in pharmacy_codes if str(code).strip()]
    if not pharmacy_codes:
        pharmacy_codes = ["apteka_ru"]
    total = len(queries)
    total *= len(pharmacy_codes)

    status["progress"]["total"] = total
    write_json(status_path(job_id), status)

    driver = None
    farmacia24_parser = None
    all_items: List[Dict] = []

    def cancel_requested() -> bool:
        return bool(read_json(status_path(job_id)).get("cancelled"))

    def finalize_cancel() -> None:
        status["status"] = "cancelled"
        status["finished_at"] = now_iso()
        write_json(status_path(job_id), status)

        write_json(result_path(job_id), {"job_id": job_id, "ready": True, "items": all_items, "cancelled": True})
        _write_result_csv(job_id, all_items, status, selected_city)
        job_log(job_id, "JOB cancelled by user")

    try:
        if "apteka_ru" in pharmacy_codes:
            driver = make_driver()
            recover_to_home(driver)
            close_modal_if_any(driver, timeout=2)
            select_city(driver, selected_city, timeout=8)

        if "farmacia24" in pharmacy_codes:
            farmacia24_parser = Farmacia24Parser()

        for q in queries:
            if cancel_requested():
                finalize_cancel()
                return
            
            if isinstance(q, str):
                q_name = q
                q_qty = None
                q_dosage = None
                q_sum = False
                raw = q
                q_barcode = ""
                q_product_code = ""
                q_manufacturer = extract_query_manufacturer(str(raw or ""))
            else:
                q_name = (q.get("name")or "").strip()
                q_qty = q.get("qty", None)
                q_dosage = q.get("dosage", None)
                q_sum = bool(q.get("qty_is_sum", False))
                raw = q.get("raw") or q.get("row") or q_name
                q_barcode = (q.get("barcode") or "").strip()
                q_product_code = (q.get("product_code") or "").strip()
                q_manufacturer = (q.get("manufacturer") or "").strip()
                if not q_manufacturer:
                    q_manufacturer = extract_query_manufacturer(str(raw or ""))

            if not q_name:
                status["progress"]["processed"] += len(pharmacy_codes)
                status["progress"]["not_found"] += len(pharmacy_codes)
                write_json(status_path(job_id), status)
                continue

            for pharmacy_code in pharmacy_codes:
                query_parts = [f"Аптека: {pharmacy_code}", f"Название: {q_name}"]
                query_parts.append(f"RAW: {raw}" if raw else "RAW: —")
                query_parts.append(f"Кол-во: {q_qty}" if q_qty is not None else "Кол-во: —")
                query_parts.append(f"Дозировка: {q_dosage}" if q_dosage else "Дозировка: —")
                query_parts.append(f"Производитель: {q_manufacturer}" if q_manufacturer else "Производитель: —")
                query_parts.append(f"ШК: {q_barcode}" if q_barcode else "ШК: —")
                query_parts.append(f"Код товара: {q_product_code}" if q_product_code else "Код товара: —")
                job_log(job_id, f"Запрос: {' | '.join(query_parts)}")

                if pharmacy_code == "apteka_ru":
                    if driver is None:
                        raise RuntimeError("Apteka driver is not initialized")
                    outcome, items = parse_one_query(
                        driver,
                        q_name,
                        PARSE_TIMEOUT,
                        PARSE_MAX_RETRIES,
                        expected_qty=q_qty,
                        expected_dosage=q_dosage,
                        qty_is_sum=q_sum,
                        raw_input=raw,
                        query_barcode=q_barcode,
                        query_product_code=q_product_code,
                        query_manufacturer=q_manufacturer,
                        job_id=job_id,
                    )
                elif pharmacy_code == "farmacia24":
                    if farmacia24_parser is None:
                        raise RuntimeError("Farmacia24 parser is not initialized")
                    farmacia24_log(
                        job_id,
                        " | ".join(
                            [
                                f"Запрос: {q_name}",
                                f"RAW: {raw if raw else '—'}",
                                f"Кол-во: {q_qty if q_qty is not None else '—'}",
                                f"Дозировка: {q_dosage if q_dosage else '—'}",
                                f"Производитель: {q_manufacturer if q_manufacturer else '—'}",
                                f"ШК: {q_barcode if q_barcode else '—'}",
                                f"Код товара: {q_product_code if q_product_code else '—'}",
                            ]
                        ),
                    )
                    outcome_data = farmacia24_parser.parse_one(
                        ParseQuery(
                            name=q_name,
                            raw=str(raw or ""),
                            qty=q_qty,
                            dosage=str(q_dosage or ""),
                            manufacturer=q_manufacturer,
                            barcode=q_barcode,
                            product_code=q_product_code,
                        ),
                        ParseContext(
                            job_id=job_id,
                            city=selected_city,
                            timeout=PARSE_TIMEOUT,
                            max_retries=PARSE_MAX_RETRIES,
                        ),
                    )
                    outcome = outcome_data.status
                    items = [
                        {
                            "source_pharmacy": item.source_pharmacy or "farmacia24",
                            "status": item.status,
                            "title": item.title,
                            "price": item.price,
                            "href": item.href,
                            "raw": raw,
                            "input_name": q_name,
                            "input_barcode": q_barcode,
                            "input_product_code": q_product_code,
                            "input_qty": (item.payload or {}).get("input_qty", q_qty),
                            "input_dosage": (item.payload or {}).get("input_dosage", q_dosage),
                            "found_qty": (item.payload or {}).get("found_qty"),
                            "found_dosage": (item.payload or {}).get("found_dosage"),
                            "found_brand": (item.payload or {}).get("found_brand"),
                            "message": ((item.payload or {}).get("message") or outcome_data.error or "").strip(),
                            "name_score": (item.payload or {}).get("name_score"),
                            "partial_name_match": (item.payload or {}).get("partial_name_match"),
                            "dosage_similarity_percent": (item.payload or {}).get("dosage_similarity_percent"),

                        }
                        for item in outcome_data.items
                    ]
                    if outcome == "not_found" and not items:
                        items = [
                            {
                                "source_pharmacy": "farmacia24",
                                "status": "not_found",
                                "title": "Не найдено",
                                "price": "",
                                "href": "",
                                "raw": raw,
                                "input_name": q_name,
                                "input_barcode": q_barcode,
                                "input_product_code": q_product_code,
                                "input_qty": q_qty,
                                "input_dosage": q_dosage,
                                "message": (outcome_data.error or "").strip() or "Результаты не найдены",
                            }
                        ]
                    if outcome_data.error and not items:
                        items = [{
                            "source_pharmacy": "farmacia24",
                            "raw": raw,
                            "input_name": q_name,
                            "input_barcode": q_barcode,
                            "input_product_code": q_product_code,
                            "input_qty": q_qty,
                            "input_dosage": q_dosage,
                            "message": outcome_data.error,
                        }]
                    if outcome == "matched" and items:
                        first_item = items[0]
                        farmacia24_log(
                            job_id,
                            " | ".join(
                                [
                                    f"Статус: {outcome}",
                                    f"Найдено: {(first_item.get('title') or '').strip() or '—'}",
                                    f"Цена: {(first_item.get('price') or '').strip() or '—'}",
                                    f"Ссылка: {(first_item.get('href') or '').strip() or '—'}",
                                ]
                            ),
                        )
                    elif outcome == "not_found":
                        reason = (outcome_data.error or "").strip() or "Результаты не найдены"
                        farmacia24_log(job_id, f"Статус: not_found | Причина: {reason}")
                    else:
                        farmacia24_log(
                            job_id,
                            f"Статус: failed | Ошибка: {(outcome_data.error or '').strip() or 'неизвестная причина'}",
                        )
                else:
                    outcome, items = "failed", []

                if cancel_requested():
                    finalize_cancel()
                    return

                found_title = "Не найдено"
                found_brand = ""
                found_message = ""
                found_qty = None
                found_dosage = ""
                found_href = ""
                if outcome == "matched" and items:
                    first_title = (items[0].get("title") or "").strip()
                    if first_title:
                        found_title = first_title
                    found_brand = (items[0].get("found_brand") or "").strip()
                    found_message = (items[0].get("message") or "").strip()
                    found_qty = items[0].get("found_qty")
                    found_dosage = (items[0].get("found_dosage") or "").strip()
                    found_href = (items[0].get("href") or "").strip()
                if outcome == "matched":
                    details_parts = [
                        f"Аптека: {pharmacy_code}",
                        f"Найдено: {found_title}",
                        f"Кол-во: {found_qty if found_qty is not None else '—'} (ожидалось: {q_qty if q_qty is not None else '—'})",
                        f"Дозировка: {found_dosage or '—'} (ожидалось: {q_dosage or '—'})",
                        f"Производитель: {found_brand or '—'} (ожидалось: {q_manufacturer or '—'})",
                    ]
                    if found_message:
                        details_parts.append(f"Детали: {found_message}")
                    if found_href:
                        details_parts.append(f"href: {found_href}")
                    job_log(job_id, " | ".join(details_parts))
                else:
                    if outcome == "failed":
                        fail_reason = (items[0].get("message") or "").strip() if items else ""
                        if fail_reason:
                            job_log(job_id, f"Аптека: {pharmacy_code} | Ошибка: {fail_reason}")
                        else:
                            job_log(job_id, f"Аптека: {pharmacy_code} | Ошибка: неизвестная причина")
                    else:
                        job_log(job_id, f"Аптека: {pharmacy_code} | Найдено: {found_title}")
                if outcome == "matched":
                    status["progress"]["matched"] += 1
                    all_items.extend(items)
                elif outcome == "not_found":
                    status["progress"]["not_found"] += 1
                    all_items.extend(items)
                else:
                    status["progress"]["failed"] += 1

                status["progress"]["processed"] += 1
                write_json(status_path(job_id), status)

                time.sleep(PARSE_PAUSE)

                if cancel_requested():
                    finalize_cancel()
                    return

        write_json(result_path(job_id), {"job_id": job_id, "ready": True, "items": all_items})

        _write_result_csv(job_id, all_items, status, selected_city)

        if cancel_requested():
            finalize_cancel()
            return
        
        status["status"] = "done"
        status["finished_at"] = now_iso()
        write_json(status_path(job_id), status)

    except Exception as e:
        status = read_json(status_path(job_id))
        status["status"] = "failed"
        status["finished_at"] = now_iso()
        status["error"] = str(e)
        write_json(status_path(job_id), status)

        write_json(result_path(job_id), {"job_id": job_id, "ready": True, "items": all_items, "error": str(e)})

        try:
            _write_result_csv(job_id, all_items, status, selected_city)
        except Exception:
            pass

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        if farmacia24_parser is not None:
            try:
                farmacia24_parser.close()
            except Exception:
                pass


async def worker_loop(queue: JobQueue, stop_event: asyncio.Event) -> None:
    """Непрерывно обрабатывает задачи из очереди до остановки."""
    while not stop_event.is_set():
        try:
            job_id = await asyncio.wait_for(queue.dequeue(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
            
        try:
            await process_job(job_id)
        finally:
            queue.task_done()


def job_log(job_id: str, msg: str) -> None:
    """Добавляет строку в лог задачи."""
    p = log_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(ZoneInfo('Asia/Irkutsk')).strftime('%d-%m %H:%M')} | {msg}\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


def search_log(job_id: str, msg: str) -> None:
    """Добавляет строку в отдельный лог поисковых переходов."""
    p = search_log_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(ZoneInfo('Asia/Irkutsk')).strftime('%d-%m %H:%M:%S')} | {msg}\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


def pharmeconom_log(job_id: str, msg: str) -> None:
    """Добавляет строку в отдельный лог ответов Pharmeconom API."""
    from app.core.storage import pharmeconom_log_path as _pharmeconom_log_path

    p = _pharmeconom_log_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(ZoneInfo('Asia/Irkutsk')).strftime('%d-%m %H:%M:%S')} | {msg}\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


def normalization_log(job_id: str, msg: str) -> None:
    """Добавляет строку в отдельный лог нормализации названий."""
    p = normalization_log_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(ZoneInfo('Asia/Irkutsk')).strftime('%d-%m %H:%M:%S')} | {msg}\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


def farmacia24_log(job_id: str, msg: str) -> None:
    """Добавляет строку в отдельный лог парсинга farmacia24."""
    p = farmacia24_log_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(ZoneInfo('Asia/Irkutsk')).strftime('%d-%m %H:%M:%S')} | {msg}\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


def _write_result_csv(job_id: str, all_items: List[Dict], status: Dict, city_name: str = "") -> None:
    """Пишет итоговый XLSX: сначала пытается обогатить исходную таблицу, иначе пишет плоскую таблицу."""
    filename = status.get("filename")
    if filename:
        src = upload_path(job_id, filename)
        if src.exists():
            try:
                build_enriched_xlsx(str(src), str(result_file_path(job_id)), all_items, city_name)
                return
            except Exception as exc:
                job_log(job_id, f"Failed to build enriched xlsx: {exc}")

    build_flat_xlsx(str(result_file_path(job_id)), all_items, city_name)
