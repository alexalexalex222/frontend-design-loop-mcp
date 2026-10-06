"""Bounded background jobs for MCP clients with short tool-call deadlines."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Job:
    task: asyncio.Task
    started: float


class JobRegistry:
    def __init__(self, limit: int = 4, retained: int = 20):
        self.limit = limit
        self.retained = retained
        self.jobs: dict[str, Job] = {}

    def start(self, operation: Callable[[], Awaitable[Any]]) -> dict:
        if sum(not job.task.done() for job in self.jobs.values()) >= self.limit:
            raise ValueError(f"At most {self.limit} design jobs may run at once")
        for key in list(self.jobs):
            if len(self.jobs) < self.retained:
                break
            if self.jobs[key].task.done():
                del self.jobs[key]
        key = uuid.uuid4().hex[:12]
        task = asyncio.create_task(operation(), name=f"frontend-design-{key}")
        # Consume completion exceptions even if the client never polls this job.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        self.jobs[key] = Job(task=task, started=time.time())
        return {"job_id": key, "status": "running", "persistence": "MCP server lifetime"}

    def status(self, key: str) -> dict:
        if key not in self.jobs:
            raise ValueError("Unknown job_id; jobs are local to this running MCP server")
        job = self.jobs[key]
        result = {"job_id": key, "elapsed_s": round(time.time() - job.started, 2)}
        if not job.task.done():
            return {**result, "status": "running"}
        if job.task.cancelled():
            return {**result, "status": "cancelled"}
        error = job.task.exception()
        if error is not None:
            return {**result, "status": "failed", "error": str(error)}
        return {**result, "status": "complete", "result": job.task.result()}

    async def shutdown(self) -> None:
        tasks = [job.task for job in self.jobs.values() if not job.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel(self, key: str) -> dict:
        if key not in self.jobs:
            raise ValueError("Unknown job_id")
        task = self.jobs[key].task
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        state = self.status(key)
        if not task.done():
            state["status"] = "cancelling"
        return state
