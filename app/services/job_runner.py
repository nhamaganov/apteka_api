import asyncio
from datetime import datetime, timezone
from typing import Dict, List

from app.core.settings import PARSE_MAX_RETRIES, PARSE_PAUSE, PARSE_TIMEOUT
from app.core.storage import result_csv_path, status_path, result_path, queries_path, read_json, write_json
from app.core.queue import JobQueue
from app.core.utils import write_csv
from app.services.apteka_parser import make_driver, recover_to_home, close_modal_if_any, parse_one_query


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def process_job(job_id: str) -> None:
    status = read_json(status_path(job_id))
    status["status"] = "running"
    status["started_at"] = now_iso()
    status["finished_at"] = None
    status["error"] = None
    write_json(status_path(job_id), status)

    queries_data = read_json(queries_path(job_id))
    queries: List[str] = queries_data.get("queries", [])
    total = len(queries)

    status["progress"]["total"] = total
    write_json(status_path(job_id), status)

    driver = None
    all_items: List[Dict] = []
    
    try:
        driver = make_driver()
        recover_to_home(driver)
        close_modal_if_any(driver, timeout=2)

        for q in queries:
            outcome, items = parse_one_query(driver, q, PARSE_TIMEOUT, PARSE_MAX_RETRIES)

            if outcome == "matched":
                status["progress"]["matched"] += 1
                all_items.extend(items)
            elif outcome == "not_found":
                status["progress"]["not_found"] += 1
            else:
                status["progress"]["failed"] += 1
            
            status["progress"]["processed"] += 1
            write_json(status_path(job_id), status)

            await asyncio.sleep(PARSE_PAUSE)

        write_json(result_path(job_id), {"job_id": job_id, "ready": True, "items": all_items})

        write_csv(result_csv_path(job_id), all_items)

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
            write_csv(result_csv_path(job_id), all_items)
        except Exception:
            pass

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


async def worker_loop(queue: JobQueue, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            job_id = await asyncio.wait_for(queue.dequeue(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
            
        try:
            await process_job(job_id)
        finally:
            queue.task_done()