import asyncio
from datetime import datetime
from uuid import uuid4

from .models import DownloadRequest, TaskSnapshot, TaskStatus


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskSnapshot] = {}
        self._lock = asyncio.Lock()

    async def create(self, request: DownloadRequest) -> TaskSnapshot:
        now = datetime.now()
        task = TaskSnapshot(
            task_id=uuid4().hex,
            status=TaskStatus.QUEUED,
            title=request.title,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._tasks[task.task_id] = task
        return task

    async def get(self, task_id: str) -> TaskSnapshot | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def update(self, task_id: str, **changes: object) -> TaskSnapshot:
        async with self._lock:
            task = self._tasks[task_id]
            updated = task.model_copy(
                update={**changes, "updated_at": datetime.now()},
                deep=True,
            )
            self._tasks[task_id] = updated
            return updated

