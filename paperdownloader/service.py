import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .config import get_settings
from .models import DownloadRequest, DownloadResponse, TaskSnapshot, TaskStatus
from .task_store import TaskStore
from .workflow import ScholarDownloadWorkflow


def api_token() -> str:
    path = Path(".state/api-token")
    path.parent.mkdir(exist_ok=True, mode=0o700)
    try:
        with path.open("x", encoding="utf-8") as file:
            path.chmod(0o600)
            file.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return path.read_text(encoding="utf-8").strip()


store = TaskStore()
workers: set[asyncio.Task] = set()
# ponytail: one browser profile requires sequential jobs; use separate profiles if needed.
queue_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.token = api_token()
    yield
    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


async def authorize(authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization.encode(), f"Bearer {app.state.token}".encode()):
        raise HTTPException(401, "请在插件设置中填写本地服务配对码")


app = FastAPI(title="SJTU Paper Downloader", lifespan=lifespan, dependencies=[Depends(authorize)])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://[a-p]{32}",
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


@app.get("/health")
async def health():
    return {"ok": True, "headless_default": get_settings().headless}


@app.post("/download", response_model=DownloadResponse)
async def create_download(request: DownloadRequest):
    if len(workers) >= 100:
        raise HTTPException(429, "下载队列已满，请等待")
    task = await store.create(request)
    worker = asyncio.create_task(run_task(task.task_id, request))
    workers.add(worker)
    worker.add_done_callback(workers.discard)
    return DownloadResponse(task_id=task.task_id, status=task.status)


@app.get("/tasks/{task_id}", response_model=TaskSnapshot)
async def get_task(task_id: str):
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在（服务重启后任务列表会清空）")
    return task


async def run_task(task_id: str, request: DownloadRequest):
    async with queue_lock:
        await store.update(task_id, status=TaskStatus.RUNNING)
        try:
            async def progress(step):
                await store.update(task_id, step=step)
            result = await ScholarDownloadWorkflow(get_settings(), progress).run(
                request.title, doi=request.doi, headless=request.headless)
            await store.update(task_id, status=TaskStatus.SUCCESS, step="下载完成",
                               result_path=result.path, metadata=result.metadata)
        except Exception as exc:
            await store.update(task_id, status=TaskStatus.ERROR, step="失败", error=str(exc))
