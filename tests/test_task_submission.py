"""Tests for task submission API."""

import asyncio
from typing import AsyncGenerator
import pytest

from deepiri_zepgpu.api.submit import TaskSubmitter
from deepiri_zepgpu.core.task import TaskPriority


@pytest.fixture
async def submitter() -> AsyncGenerator[TaskSubmitter, None]:
    """Create a test submitter."""
    submitter = TaskSubmitter(auto_start=True)
    await submitter.start()
    yield submitter
    await submitter.stop()


class TestTaskSubmission:
    """Test cases for task submission."""

    @pytest.mark.asyncio
    async def test_submit_simple_task(self, submitter: TaskSubmitter) -> None:
        """Test submitting a simple task."""
        def dummy() -> str:
            return "hello"

        task_id = await submitter.submit(dummy)
        assert task_id is not None

    @pytest.mark.asyncio
    async def test_submit_with_priority(self, submitter: TaskSubmitter) -> None:
        """Test submitting with priority."""
        def dummy() -> int:
            return 42

        task_id = await submitter.submit(dummy, priority=TaskPriority.HIGH)
        assert task_id is not None

    @pytest.mark.asyncio
    async def test_submit_with_resources(self, submitter: TaskSubmitter) -> None:
        """Test submitting with resource requirements."""
        def dummy() -> int:
            return 42

        task_id = await submitter.submit(
            dummy,
            gpu_memory_mb=4096,
            timeout_seconds=1800,
        )
        assert task_id is not None

    @pytest.mark.asyncio
    async def test_get_task(self, submitter: TaskSubmitter) -> None:
        """Test getting task by ID."""
        def dummy() -> int:
            return 42

        task_id = await submitter.submit(dummy)
        task = submitter.get_task(task_id)
        assert task is not None
        assert task.task_id == task_id

    @pytest.mark.asyncio
    async def test_list_tasks(self, submitter: TaskSubmitter) -> None:
        """Test listing tasks."""
        def dummy() -> int:
            return 42

        for _ in range(3):
            await submitter.submit(dummy)

        tasks = submitter.list_tasks()
        assert len(tasks) >= 3

    @pytest.mark.asyncio
    async def test_cancel_task(self, submitter: TaskSubmitter) -> None:
        """Test cancelling a task."""
        def dummy() -> int:
            import time
            time.sleep(10)
            return 42

        task_id = await submitter.submit(dummy)
        result = submitter.cancel_task(task_id)
        assert result is True
