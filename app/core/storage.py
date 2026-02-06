import json
import os

from pathlib import Path
import shutil
from typing import Any, Dict, List
from datetime import datetime

JOB_STORE = Path(os.environ.get("JOB_STORE", "job_store")).resolve()


def ensure_job_store() -> None:
    JOB_STORE.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    return JOB_STORE / job_id


def status_path(job_id: str) -> Path:
    return job_dir(job_id) / "status.json"


def result_path(job_id: str) -> Path:
    return job_dir(job_id) / "result.json"


def upload_path(job_id: str, filename: str) -> Path:
    safe_name = Path(filename).name
    return job_dir(job_id) / safe_name


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def queries_path(job_id: str) -> Path:
    return job_dir(job_id) / "queries.json"


def result_csv_path(job_id: str) -> Path:
    return job_dir(job_id) / "result.csv"


def log_path(job_id: str) -> Path:
    return job_dir(job_id) / "runner.log"


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
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
            data["created_at"] = datetime.fromisoformat(data["created_at"]).strftime("%d-%m-%Y %H:%M:%S")
            jobs.append(data)

        except Exception:
            continue

    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jobs[:limit]


def delete_job(job_id: str) -> bool:
    p = job_dir(job_id)
    if not p.exists():
        return False 
    shutil.rmtree(p, ignore_errors=True)
    return True
