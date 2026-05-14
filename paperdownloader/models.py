from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class DownloadRequest(BaseModel):
    title: str = Field(min_length=3)
    scholar_url: HttpUrl | None = None
    headless: bool | None = None


class DownloadResponse(BaseModel):
    task_id: str
    status: TaskStatus


class CaptchaSubmission(BaseModel):
    text: str = Field(min_length=1, max_length=12)


class TaskSnapshot(BaseModel):
    task_id: str
    status: TaskStatus
    title: str
    created_at: datetime
    updated_at: datetime
    step: str = "queued"
    error: str | None = None
    result_path: Path | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    path: Path | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtensionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    headless: bool = True
    download_dir: str | None = Field(default=None, alias="downloadDir")
    captcha_model_path: str | None = Field(default=None, alias="captchaModelPath")
