from datetime import datetime, timezone
from pathlib import Path
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException, Request

from app.core.storage import (
    ensure_job_store, job_dir, upload_path, status_path, result_path, write_json, read_json, queries_path
)
from app.core.models import JobProgress, JobStatus
from app.utils.xls import extract_queries_from_excel


router = APIRouter()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/", response_model=JobStatus)
async def create_job(request: Request, file: UploadFile = File(...)):
    ensure_job_store()

    ext = Path(file.filename).suffix.lower()
    if ext not in {".xls", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Upload .xls or .xlsx file")

    job_id = uuid.uuid4().hex
    job_dir(job_id).mkdir(parents=True, exist_ok=True)

    dst = upload_path(job_id, file.filename)
    content = await file.read()
    dst.write_bytes(content)

    try:
        queries = extract_queries_from_excel(str(dst))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse excel: {e}")
    
    write_json(queries_path(job_id), {"queries": queries})


    status = JobStatus(
        job_id=job_id,
        status="queued",
        progress=JobProgress(total=len(queries)),
        created_at=now_iso(),
    )

    write_json(status_path(job_id), status.model_dump())
    write_json(result_path(job_id), {"job_id": job_id, "ready": False, "items": []})
    
    await request.app.state.queue.enqueue(job_id)

    return status


@router.get("/{job_id}", response_model=JobStatus)
def get_job_status(job_id: str):
    p = status_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    data = read_json(p)
    return JobStatus(**data)


@router.get("/{job_id}/result")
def get_job_result(job_id: str):
    p = result_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return read_json(p)