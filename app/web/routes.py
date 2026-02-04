from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import uuid

from app.core.storage import (
    ensure_job_store, job_dir, upload_path, status_path, result_path, queries_path,
    write_json
)
from app.core.models import JobStatus, JobProgress
from app.core.time import now_iso
from app.utils.xls import extract_queries_from_excel


router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    ensure_job_store()

    ext = Path(file.filename).suffix.lower()
    if ext not in {".xls", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Загрузи .xls или .xlsx")

    job_id = uuid.uuid4().hex
    job_dir(job_id).mkdir(parents=True, exist_ok=True)

    dst = upload_path(job_id, file.filename)
    dst.write_bytes(await file.read())

    try:
        queries = extract_queries_from_excel(str(dst))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не смог прочитать Excel: {e}")

    write_json(queries_path(job_id), {"queries": queries})

    status = JobStatus(
        job_id=job_id,
        status="queued",
        progress=JobProgress(total=len(queries)),
        created_at=now_iso(),
    )
    write_json(status_path(job_id), status.model_dump())
    write_json(result_path(job_id), {"job_id": job_id, "ready": False, "items": []})

    # 🔥 кладём job в очередь воркера
    await request.app.state.queue.enqueue(job_id)

    # редирект на страницу прогресса
    return RedirectResponse(url=f"/ui/{job_id}", status_code=303)


@router.get("/ui/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    # страница прогресса, JS сам будет опрашивать /jobs/{job_id}
    return templates.TemplateResponse("job.html", {"request": request, "job_id": job_id})