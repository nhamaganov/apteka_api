from fastapi import FastAPI
from app.api.routes_jobs import router as jobs_router
from app.core.storage import ensure_job_store
from contextlib import asynccontextmanager


app = FastAPI(title="Parser", version="0.1.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_job_store()
    yield


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def on_startup():
    ensure_job_store()


@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])