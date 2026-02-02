import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.storage import status_path, result_path, queries_path, read_json, write_json
from app.core.queue import JobQueue


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def process_job(job_id: str) -> None:
    status = read_json(status_path(job_id))
    status["status"] = "running"
    status["started_at"] = now_iso()
    status["error"] = None
    write_json(status_path(job_id), status)

    queries_data = read_json(queries_path(job_id))
    queries = queries_data.get("queries", [])
    total = len(queries)

    status["progress"]["total"] = total
    write_json(status_path(job_id), status)

    items = []

    for q in queries:
        await asyncio.sleep(0.05)

        if (status["progress"]["processed"] + 1) % 3 == 0:
            status["progress"]["matched"] += 1
            items.append({"input_name": q, "title": f"FAKE {q}", "price": "123"})
        else:
            status["progress"]["not_found"] += 1
        
        status["progress"]["processed"] += 1
        write_json(status_path(job_id), status)

    write_json(result_path(job_id), {"job_id": job_id, "ready": True, "items": items})

    status["status"] = "done"
    status["finished_at"] = now_iso()
    write_json(status_path(job_id), status)


async def worker_loop(queue: JobQueue, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            job_id = await asyncio.wait_for(queue.dequeue(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
            
        try:
            await process_job(job_id)
        except Exception as e:
            st = read_json(status_path(job_id))
            st["status"] = "failed"
            st["finished_at"] = now_iso()
            st["error"] = str(e)
            st["progress"]["failed"] += 1
            write_json(status_path(job_id), st)
        finally:
            queue.task_done()