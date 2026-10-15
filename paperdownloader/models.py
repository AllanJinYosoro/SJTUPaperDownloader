from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator

from .textmatch import clean_doi


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class DownloadRequest(BaseModel):
    title: str = Field(min_length=3)
    doi: str = ""
    scholar_url: HttpUrl | None = None
    headless: bool | None = None

    @field_validator("doi")
    @classmethod
    def validate_doi(cls, value: str) -> str:
        return clean_doi(value)


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
