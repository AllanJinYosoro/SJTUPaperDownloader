import asyncio
import base64
import json
import platform
import struct
import sys
from typing import Any

from pydantic import ValidationError

from . import __version__
from .captcha import JAccountCaptchaSolver
from .config import Settings, apply_extension_config, get_settings
from .models import (
    CaptchaSubmission,
    DownloadRequest,
    DownloadResponse,
    ExtensionConfig,
    TaskStatus,
)
from .task_store import TaskStore
from .workflow import ScholarDownloadWorkflow


class NativeHost:
    def __init__(self, settings: Settings | None = None) -> None:
        self._base_settings = settings or get_settings()
        self._extension_config = ExtensionConfig()
        self._store = TaskStore()
        self._pending_captchas: dict[str, asyncio.Future[str]] = {}

    async def run(self) -> None:
        while True:
            message = await asyncio.to_thread(read_message)
            if message is None:
                return
            response = await self.handle_message(message)
            write_message(response)

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        request_id = str(message.get("id") or "")
        message_type = message.get("type")
        payload = message.get("payload") or {}

        try:
            if message_type == "updateConfig":
                data = self._update_config(payload)
            elif message_type == "getConfig":
                data = self._config_snapshot()
            elif message_type == "health":
                data = self._health_snapshot()
            elif message_type == "startDownload":
                data = await self._start_download(payload)
            elif message_type == "getTask":
                data = await self._get_task(payload)
            elif message_type == "submitCaptcha":
                data = await self._submit_captcha(payload)
            else:
                raise RuntimeError(f"Unknown message type: {message_type!r}")
            return {"id": request_id, "ok": True, "data": data}
        except ValidationError as exc:
            return {"id": request_id, "ok": False, "error": exc.errors()[0]["msg"]}
        except Exception as exc:  # noqa: BLE001
            return {"id": request_id, "ok": False, "error": str(exc)}

    def _update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._extension_config = ExtensionConfig.model_validate(payload)
        return self._config_snapshot()

    def _effective_settings(self) -> Settings:
        return apply_extension_config(self._base_settings, self._extension_config)

    def _solver(self, settings: Settings) -> JAccountCaptchaSolver:
        return JAccountCaptchaSolver(settings)

    def _config_snapshot(self) -> dict[str, Any]:
        settings = self._effective_settings()
        config = ExtensionConfig(
            headless=settings.headless,
            downloadDir=str(settings.download_dir),
            captchaModelPath=str(settings.captcha_model_path),
        )
        return config.model_dump(by_alias=True)

    def _health_snapshot(self) -> dict[str, Any]:
        settings = self._effective_settings()
        solver = self._solver(settings)
        return {
            "ok": True,
            "host_version": __version__,
            "platform": platform.system(),
            "captcha_model_available": solver.available(),
            "config": self._config_snapshot(),
        }

    async def _start_download(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self._effective_settings()
        request = DownloadRequest.model_validate(
            {
                "title": payload.get("title"),
                "scholar_url": payload.get("scholarUrl"),
                "headless": payload.get("headless", settings.headless),
            }
        )
        task = await self._store.create(request)
        asyncio.create_task(self._run_task(task.task_id, request, settings))
        return DownloadResponse(task_id=task.task_id, status=task.status).model_dump(mode="json")

    async def _get_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("taskId") or "")
        task = await self._store.get(task_id)
        if task is None:
            raise RuntimeError("Task not found")
        return task.model_dump(mode="json")

    async def _submit_captcha(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("taskId") or "")
        submission = CaptchaSubmission.model_validate({"text": payload.get("text")})
        task = await self._store.get(task_id)
        if task is None:
            raise RuntimeError("Task not found")
        future = self._pending_captchas.get(task_id)
        if future is None or future.done():
            raise RuntimeError("Task is not waiting for captcha input")

        future.set_result(submission.text.strip())
        metadata = dict(task.metadata)
        metadata.update({"captcha_required": False, "captcha_image": None})
        updated = await self._store.update(
            task_id,
            step="received human captcha",
            metadata=metadata,
        )
        return updated.model_dump(mode="json")

    async def _run_task(
        self,
        task_id: str,
        request: DownloadRequest,
        settings: Settings,
    ) -> None:
        await self._store.update(task_id, status=TaskStatus.RUNNING, step="starting browser")
        try:
            await self._store.update(task_id, step="navigating SJTU library")
            workflow = ScholarDownloadWorkflow(
                settings,
                self._solver(settings),
                captcha_prompt=lambda image_bytes: self._request_human_captcha(task_id, image_bytes),
            )
            result = await workflow.run(request.title, headless=request.headless)
            await self._store.update(
                task_id,
                status=TaskStatus.SUCCESS,
                step="download completed",
                result_path=result.path,
                metadata=result.metadata,
            )
        except Exception as exc:  # noqa: BLE001
            await self._store.update(
                task_id,
                status=TaskStatus.ERROR,
                step="failed",
                error=str(exc),
            )
        finally:
            pending = self._pending_captchas.pop(task_id, None)
            if pending is not None and not pending.done():
                pending.cancel()

    async def _request_human_captcha(self, task_id: str, image_bytes: bytes) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending_captchas[task_id] = future
        image_data = base64.b64encode(image_bytes).decode("ascii")

        task = await self._store.get(task_id)
        metadata = dict(task.metadata) if task else {}
        metadata.update(
            {
                "captcha_required": True,
                "captcha_image": f"data:image/png;base64,{image_data}",
            }
        )
        await self._store.update(task_id, step="waiting for human captcha", metadata=metadata)
        try:
            text = await asyncio.wait_for(future, timeout=300)
            return text.strip()
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timed out waiting for human captcha input.") from exc
        finally:
            self._pending_captchas.pop(task_id, None)


def read_message() -> dict[str, Any] | None:
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    if len(raw_length) != 4:
        raise RuntimeError("Native message length header was incomplete.")
    message_length = struct.unpack("<I", raw_length)[0]
    payload = sys.stdin.buffer.read(message_length)
    if len(payload) != message_length:
        raise RuntimeError("Native message payload was incomplete.")
    return json.loads(payload.decode("utf-8"))


def write_message(message: dict[str, Any]) -> None:
    encoded = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main() -> None:
    try:
        asyncio.run(NativeHost().run())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
