import asyncio
import time
from datetime import datetime
from typing import Dict, List

from app.core.settings import PARSE_MAX_RETRIES, PARSE_PAUSE, PARSE_TIMEOUT
from app.core.storage import log_path, result_file_path, status_path, result_path, queries_path, read_json, write_json, upload_path
from app.core.queue import JobQueue
from app.core.time import now_iso
from app.utils.xls import build_enriched_xlsx, build_flat_xlsx
from app.services.apteka_parser import make_driver, recover_to_home, close_modal_if_any, parse_one_query, select_city


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
    total = len(queries)

    status["progress"]["total"] = total
    write_json(status_path(job_id), status)

    driver = None
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
        driver = make_driver()
        recover_to_home(driver)
        close_modal_if_any(driver, timeout=2)
        select_city(driver, selected_city, timeout=8)

        for q in queries:
            if cancel_requested():
                finalize_cancel()
                return
            
            if isinstance(q, str):
                q_name = q
                q_qty = None
                q_sum = False
                raw = q
            else:
                q_name = (q.get("name")or "").strip()
                q_qty = q.get("qty", None)
                q_sum = bool(q.get("qty_is_sum", False))
                raw = q.get("raw") or q_name

            if not q_name:
                status["progress"]["processed"] += 1
                status["progress"]["not_found"] += 1
                write_json(status_path(job_id), status)
                continue

            query_line = f"{q_name} - {q_qty}" if q_qty is not None else q_name
            job_log(job_id, f"Запрос: {query_line}")

            outcome, items = parse_one_query(
                driver,
                q_name,
                PARSE_TIMEOUT,
                PARSE_MAX_RETRIES,
                expected_qty=q_qty,
                qty_is_sum=q_sum,
                raw_input=raw,
                job_id=None,
            )

            if cancel_requested():
                finalize_cancel()
                return

            found_title = "Не найдено"
            if outcome == "matched" and items:
                first_title = (items[0].get("title") or "").strip()
                if first_title:
                    found_title = first_title
            job_log(job_id, f"Найдено: {found_title}")
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
    line = f"{datetime.now().strftime('%d-%m %H:%M')} | {msg}\n"
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
