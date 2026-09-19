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
    title: str = Field(min_length=3, max_length=2000)
    doi: str = Field(default="", max_length=512)
    scholar_url: HttpUrl | None = None
    headless: bool | None = None

    @field_validator("doi")
    @classmethod
    def normalize_doi(cls, value: str) -> str:
        return clean_doi(value)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("Title must have at least three characters")
        return value


class DownloadResponse(BaseModel):
    task_id: str
    status: TaskStatus


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
    path: Path
    metadata: dict[str, Any] = Field(default_factory=dict)
