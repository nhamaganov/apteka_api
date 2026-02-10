import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes_jobs import router as jobs_router
from app.core.storage import ensure_job_store
from app.core.queue import JobQueue
from app.services.job_runner import worker_loop
from app.web.routes import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управляет жизненным циклом приложения для запуска и остановки воркера."""
    ensure_job_store()

    app.state.queue = JobQueue()
    app.state.stop_event = asyncio.Event()
    app.state.worker_task = asyncio.create_task(worker_loop(app.state.queue, app.state.stop_event))

    yield

    app.state.stop_event.set()
    app.state.worker_task.cancel()
    try:
        await app.state.worker_task
    except Exception:
        pass


app = FastAPI(title="Parser", version="0.2.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

app.include_router(web_router)

@app.get("/health")
def health():
    """Простой health-check эндпоинт."""
    return {"status": "ok"}

app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
