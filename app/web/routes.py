import json

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import uuid

from app.core.storage import (
    delete_job, ensure_job_store, job_dir, list_jobs, read_json, upload_path, status_path, result_path, queries_path,
    write_json
)
from app.core.models import JobStatus, JobProgress
from app.core.time import now_iso
from app.services.job_runner import pharmeconom_log
from app.services.pharmeconom_client import (
    PharmeconomClient,
    PharmeconomClientError,
    build_queries_from_product_info,
    fetch_product_info_rows,
)
from app.utils.xls import extract_product_codes_from_excel
from app.core.naming import make_display_name


router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Рендерит страницу со списком задач."""
    jobs = list_jobs()
    

    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request,
            "jobs": jobs,
        }
    )


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), city: str = Form("Иркутск")):
    """Обрабатывает загрузку Excel в UI и ставит задачу в очередь."""
    ensure_job_store()

    ext = Path(file.filename).suffix.lower()
    if ext not in {".xls", ".xlsx", ".ods"}:
        raise HTTPException(status_code=400, detail="Загрузи .xls, .xlsx или .ods")

    job_id = uuid.uuid4().hex
    job_dir(job_id).mkdir(parents=True, exist_ok=True)

    dst = upload_path(job_id, file.filename)
    dst.write_bytes(await file.read())

    try:
        rows = extract_product_codes_from_excel(str(dst))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не смог прочитать Excel: {e}")

    try:
        client = PharmeconomClient()
    except PharmeconomClientError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    product_info_items = fetch_product_info_rows(client, rows)
    queries = build_queries_from_product_info(product_info_items)

    write_json(queries_path(job_id), {"queries": queries, "city": city, "product_info": product_info_items})

    for item in product_info_items:
        if item.get("status") == "ok":
            payload = item.get("api_response") or {}
        else:
            payload = {"status": "error", "error": item.get("error", "") }
        pharmeconom_log(job_id, json.dumps(payload, ensure_ascii=False))

    display_name = make_display_name(file.filename)

    status = JobStatus(
        job_id=job_id,
        status="queued",
        progress=JobProgress(total=len(queries)),
        created_at=now_iso(),
    )
    data = status.model_dump()
    data["display_name"] = display_name
    data["filename"] = file.filename
    data["city"] = city
    data["cancelled"] = False

    write_json(status_path(job_id), data)
    write_json(result_path(job_id), {"job_id": job_id, "ready": False, "items": []})

    # 🔥 кладём job в очередь воркера
    await request.app.state.queue.enqueue(job_id)

    # редирект на страницу прогресса
    return RedirectResponse(url=f"/ui/{job_id}", status_code=303)


@router.get("/ui/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    """Рендерит страницу прогресса задачи."""
    name = None
    try:
        st = read_json(status_path(job_id))
        name = st.get("display_name") or st.get("filename")
    except Exception:
        pass

    return templates.TemplateResponse("job.html", {"request": request, "job_id": job_id, "display_name": name})


@router.post("/ui/{job_id}/cancel")
def cancel_job_ui(job_id: str):
    """Отмечает задачу отменённой и редиректит на главную."""
    stp = status_path(job_id)
    if not stp.exists():
        return RedirectResponse("/", status_code=303)

    st = read_json(stp)
    if st.get("status") not in {"done", "failed", "cancelled"}:
        st["cancelled"] = True
        write_json(stp, st)

    return RedirectResponse("/", status_code=303)


@router.post("/ui/{job_id}/delete")
def delete_job_ui(job_id: str):
    """Удаляет завершённую задачу и редиректит на главную."""
    stp = status_path(job_id)
    if not stp.exists():
        return RedirectResponse("/", status_code=303)
    st = read_json(stp)
    if st.get("status") in {"done", "failed", "cancelled"}:
        delete_job(job_id)
        
    return RedirectResponse("/", status_code=303)
