import json
import os

from pathlib import Path
import shutil
from typing import Any, Dict, List
from datetime import datetime

JOB_STORE = Path(os.environ.get("JOB_STORE", "job_store")).resolve()


def ensure_job_store() -> None:
    """Гарантирует, что папка JOB_STORE существует, создав её при необходимости"""
    JOB_STORE.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    """Возвращает путь к рабочей папке"""
    return JOB_STORE / job_id


def status_path(job_id: str) -> Path:
    """Возвращает путь к папке со статусом"""
    return job_dir(job_id) / "status.json"


def result_path(job_id: str) -> Path:
    """Возвращает путь к папке с результатом"""
    return job_dir(job_id) / "result.json"


def upload_path(job_id: str, filename: str) -> Path:
    """Возвращает путь к папке загрузки"""
    safe_name = Path(filename).name
    return job_dir(job_id) / safe_name


def write_json(path: Path, data: Dict[str, Any]) -> None:
    """
    Записывает данные во временный файл, а после передает из в json-файл.
    Гарантирует, что json не будет поврежденным
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Dict[str, Any]:
    """Читает json-файл и превращает в словарь"""
    return json.loads(path.read_text(encoding="utf-8"))


def queries_path(job_id: str) -> Path:
    """Возвращает путь к файлу с запросами"""
    return job_dir(job_id) / "queries.json"


def result_file_path(job_id: str) -> Path:
    """Возвращает путь к файлу с результатами"""
    return job_dir(job_id) / "result.xlsx"


def log_path(job_id: str) -> Path:
    """Возвращает путь к файлу с логами"""
    return job_dir(job_id) / "runner.log"


def search_log_path(job_id: str) -> Path:
    """Возвращает путь к файлу с подробным логом поиска."""
    return job_dir(job_id) / "search.log"


def pharmeconom_log_path(job_id: str) -> Path:
    """Возвращает путь к отдельному логу ответов Pharmeconom API."""
    return job_dir(job_id) / "pharmeconom.log"


def normalization_log_path(job_id: str) -> Path:
    """Возвращает путь к отдельному логу нормализации названий."""
    return job_dir(job_id) / "normalization.log"


def farmacia24_log_path(job_id: str) -> Path:
    """Возвращает путь к отдельному логу парсера farmacia24."""
    return job_dir(job_id) / "farmacia24.log"


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """Возвращает список всех существующих парсингов"""
    ensure_job_store()
    jobs = []

    for p in JOB_STORE.iterdir():
        if not p.is_dir():
            continue

        st = p / "status.json"

        if  not st.exists():
            continue

        try:
            data = read_json(st)
            data["job_id"] = data.get("job_id") or p.name
            if not data.get("city"):
                q_path = p / "queries.json"
                if q_path.exists():
                    try:
                        q_data = read_json(q_path)
                        data["city"] = q_data.get("city", "")
                    except Exception:
                        data["city"] = ""

            created_at_iso = data.get("created_at", "")
            try:
                created_at_dt = datetime.fromisoformat(created_at_iso)
                data["created_at"] = created_at_dt.strftime("%d-%m-%Y %H:%M:%S")
            except (TypeError, ValueError):
                created_at_dt = datetime.min
            data["_created_at_sort"] = created_at_dt

            jobs.append(data)

        except Exception:
            continue

    jobs.sort(key=lambda x: x.get("_created_at_sort", datetime.min), reverse=True)
    for job in jobs:
        job.pop("_created_at_sort", None)

    return jobs[:limit]


def delete_job(job_id: str) -> bool:
    """Удаляет парсинг по job_id"""
    p = job_dir(job_id)
    if not p.exists():
        return False 
    shutil.rmtree(p, ignore_errors=True)
    return True
