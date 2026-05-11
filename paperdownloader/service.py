import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .captcha import JAccountCaptchaSolver
from .config import get_settings
from .models import DownloadRequest, DownloadResponse, TaskSnapshot, TaskStatus
from .task_store import TaskStore
from .workflow import ScholarDownloadWorkflow


settings = get_settings()
store = TaskStore()
captcha_solver = JAccountCaptchaSolver(settings)
workflow = ScholarDownloadWorkflow(settings, captcha_solver)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.download_dir.expanduser().mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="PaperDownloader Local Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "captcha_model_available": captcha_solver.available(),
        "headless_default": settings.headless,
    }


@app.post("/download", response_model=DownloadResponse)
async def create_download(request: DownloadRequest) -> DownloadResponse:
    task = await store.create(request)
    asyncio.create_task(_run_task(task.task_id, request))
    return DownloadResponse(task_id=task.task_id, status=task.status)


@app.get("/tasks/{task_id}", response_model=TaskSnapshot)
async def get_task(task_id: str) -> TaskSnapshot:
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _run_task(task_id: str, request: DownloadRequest) -> None:
    await store.update(task_id, status=TaskStatus.RUNNING, step="starting browser")
    try:
        await store.update(task_id, step="navigating SJTU library")
        result = await workflow.run(request.title, headless=request.headless)
        await store.update(
            task_id,
            status=TaskStatus.SUCCESS,
            step="download completed",
            result_path=result.path,
            metadata=result.metadata,
        )
    except Exception as exc:
        await store.update(
            task_id,
            status=TaskStatus.ERROR,
            step="failed",
            error=str(exc),
        )

