import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_jobs import router as jobs_router
from app.core.storage import ensure_job_store
from app.core.queue import JobQueue
from app.services.job_runner import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_job_store()

    app.state.queue = JobQueue()
    app.state.stop_event = asyncio.Event()
    app.state.worker_task = asyncio.create_task(worker_loop(app.state.queue, app.state.stop_event))

    yield

    # shutdown
    app.state.stop_event.set()
    app.state.worker_task.cancel()
    try:
        await app.state.worker_task
    except Exception:
        pass


app = FastAPI(title="Parser", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])