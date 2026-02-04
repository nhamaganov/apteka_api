import asyncio
from typing import Dict, List

from app.core.settings import PARSE_MAX_RETRIES, PARSE_PAUSE, PARSE_TIMEOUT
from app.core.storage import log_path, result_csv_path, status_path, result_path, queries_path, read_json, write_json
from app.core.queue import JobQueue
from app.core.time import now_iso
from app.core.utils import write_csv
from app.services.apteka_parser import make_driver, recover_to_home, close_modal_if_any, parse_one_query



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
            job_log(job_id, f"QUERY start: {q!r}")

            outcome, items = parse_one_query(driver, q, PARSE_TIMEOUT, PARSE_MAX_RETRIES)

            job_log(job_id, f"QUERY done: {q!r} outcome={outcome} items={len(items)}")
            if items:
                for it in items[:3]:
                    job_log(job_id, f"item: title={it.get("title")!r} price={it.get("price")!r}")
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

        job_log(
            job_id,
            f"JOB done: processed={status['progress']['processed']} "
            f"matched={status['progress']['matched']} "
            f"not_found={status['progress']['not_found']} "
            f"failed={status['progress']['failed']}"
        )

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


def job_log(job_id: str, msg: str) -> None:
    p = log_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"{now_iso()} | {msg}\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)