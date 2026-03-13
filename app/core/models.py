from pydantic import BaseModel
from typing import Optional


class JobProgress(BaseModel):
    total: int = 0
    processed: int = 0
    matched: int = 0
    not_found: int = 0
    failed: int = 0


class JobStatus(BaseModel):
    job_id: str
    status: str # queued | running | done | failed
    progress: JobProgress
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    