import uuid
from pathlib import Path

from fastapi import APIRouter, Query, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse

from app.core.naming import make_display_name
from app.core.storage import (
    ensure_job_store, job_dir, log_path, result_file_path, upload_path, status_path, result_path, write_json, read_json, queries_path
)
from app.core.models import JobProgress, JobStatus
from app.core.time import now_iso
from app.utils.xls import extract_queries_from_excel


router = APIRouter()


@router.post("/", response_model=JobStatus)
async def create_job(request: Request, file: UploadFile = File(...), city: str = Form("Иркутск")):
    """
    Создаёт новую задачу (job) на основе загруженного Excel-файла.

    Функция:
    - принимает Excel-файл (.xls или .xlsx);
    - сохраняет файл в директорию задачи;
    - извлекает запросы из Excel;
    - инициализирует статус и результаты задачи;
    - ставит задачу в очередь на обработку.

    В случае ошибки чтения или парсинга Excel-файла
    возвращает HTTP 400.

    Args:
        request (Request): объект запроса FastAPI, используется для доступа к очереди.
        file (UploadFile): загруженный Excel-файл с входными данными.

    Returns:
        JobStatus: начальный статус созданной задачи (queued).
    """
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
    
    write_json(queries_path(job_id), {"queries": queries, "city": city})

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
    
    await request.app.state.queue.enqueue(job_id)

    return status


@router.get("/{job_id}", response_model=JobStatus)
def get_job_status(job_id: str):
    """Возвращает текущий статус задачи."""
    p = status_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    data = read_json(p)
    return JobStatus(**data)


@router.get("/{job_id}/result")
def get_job_result(job_id: str):
    """Возвращает JSON-результат для задачи."""
    p = result_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return read_json(p)


@router.get("/{job_id}/download")
def download_job_result(job_id: str):
    """Отдаёт XLSX-результаты для завершённой задачи."""
    st_path = status_path(job_id)
    if not st_path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    status = read_json(st_path)
    if status.get("status") not in {"done", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Result not ready yet")
    
    p = result_file_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Result file not found")

    return FileResponse(
        path=str(p),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{job_id}.xlsx"
    )


@router.get("/{job_id}/log")
def get_job_log(job_id: str, tail: int = Query(200, ge=1, le=5000)):
    """Возвращает последние строки лога задачи."""
    p = log_path(job_id)
    if not p.exists():
        return {"job_id": job_id, "lines": []}
    
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {"job_id": job_id, "lines": []}
    
    return {"job_id": job_id, "lines": lines[-tail:]}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    """Отмечает задачу как отменённую, если она в очереди/работе."""
    p = status_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    st = read_json(p)

    if st.get("status") in {"done", "failed", "cancelled"}:
        return {"job_id": job_id, "status": st.get("status"), "cancelled": st.get("cancelled", True)}
    
    st["cancelled"] = True
    write_json(p, st)
    return {"job_id": job_id, "status": st.get("status"), "cancelled": True}
    

@router.post("/{job_id}/delete")
def delete_job_endpoint(job_id: str):
    """Удаляет завершённую задачу и её файлы."""
    p = status_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    st = read_json(p)
    if st.get("status") not in {"done", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Job is not finished. Cancel it first")
    
    from app.core.storage import delete_job
    delete_job(job_id)
    return {"ok": True, "job_id": job_id}
