import asyncio
import base64
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .captcha import JAccountCaptchaSolver
from .config import get_settings
from .models import CaptchaSubmission, DownloadRequest, DownloadResponse, TaskSnapshot, TaskStatus
from .task_store import TaskStore
from .workflow import ScholarDownloadWorkflow


settings = get_settings()
store = TaskStore()
captcha_solver = JAccountCaptchaSolver(settings)
pending_captchas: dict[str, asyncio.Future[str]] = {}


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


@app.post("/tasks/{task_id}/captcha", response_model=TaskSnapshot)
async def submit_captcha(task_id: str, submission: CaptchaSubmission) -> TaskSnapshot:
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    future = pending_captchas.get(task_id)
    if future is None or future.done():
        raise HTTPException(status_code=409, detail="Task is not waiting for captcha input")
    future.set_result(submission.text.strip())
    metadata = dict(task.metadata)
    metadata.update({"captcha_required": False, "captcha_image": None})
    return await store.update(task_id, step="received human captcha", metadata=metadata)


async def _run_task(task_id: str, request: DownloadRequest) -> None:
    await store.update(task_id, status=TaskStatus.RUNNING, step="starting browser")
    try:
        await store.update(task_id, step="navigating SJTU library")
        workflow = ScholarDownloadWorkflow(
            settings,
            captcha_solver,
            captcha_prompt=lambda image_bytes: _request_human_captcha(task_id, image_bytes),
        )
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
    finally:
        pending = pending_captchas.pop(task_id, None)
        if pending is not None and not pending.done():
            pending.cancel()


async def _request_human_captcha(task_id: str, image_bytes: bytes) -> str:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    pending_captchas[task_id] = future
    image_data = base64.b64encode(image_bytes).decode("ascii")

    task = await store.get(task_id)
    metadata = dict(task.metadata) if task else {}
    metadata.update(
        {
            "captcha_required": True,
            "captcha_image": f"data:image/png;base64,{image_data}",
        }
    )
    await store.update(task_id, step="waiting for human captcha", metadata=metadata)
    try:
        text = await asyncio.wait_for(future, timeout=300)
        return text.strip()
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Timed out waiting for human captcha input.") from exc
    finally:
        pending_captchas.pop(task_id, None)
