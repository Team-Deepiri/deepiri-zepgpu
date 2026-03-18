"""Tests for scheduler module."""

import asyncio
import pytest

from deepiri_zepgpu.core.scheduler import TaskScheduler, SchedulingPolicy
from deepiri_zepgpu.core.task import Task, TaskResources, TaskPriority
from deepiri_zepgpu.core.gpu_manager import GPUManager


@pytest.fixture
async def scheduler():
    """Create a test scheduler."""
    gpu_manager = GPUManager(enable_nvml=False)
    scheduler = TaskScheduler(gpu_manager, policy=SchedulingPolicy.PRIORITY)
    await scheduler.start()
    yield scheduler
    await scheduler.stop()


@pytest.fixture
def sample_task():
    """Create a sample task."""
    def dummy_func():
        return 42
    return Task(
        func=dummy_func,
        resources=TaskResources(gpu_memory_mb=1024),
        priority=TaskPriority.NORMAL,
        user_id="test_user",
    )


class TestTaskScheduler:
    """Test cases for TaskScheduler."""

    @pytest.mark.asyncio
    async def test_submit_task(self, scheduler, sample_task):
        """Test task submission."""
        task_id = await scheduler.submit_task(sample_task)
        assert task_id is not None
        assert len(task_id) > 0

    @pytest.mark.asyncio
    async def test_get_task(self, scheduler, sample_task):
        """Test getting task by ID."""
        task_id = await scheduler.submit_task(sample_task)
        task = scheduler.get_task(task_id)
        assert task is not None
        assert task.task_id == task_id

    @pytest.mark.asyncio
    async def test_cancel_task(self, scheduler, sample_task):
        """Test task cancellation."""
        task_id = await scheduler.submit_task(sample_task)
        result = scheduler.cancel_task(task_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_list_tasks(self, scheduler, sample_task):
        """Test listing tasks."""
        await scheduler.submit_task(sample_task)
        await scheduler.submit_task(sample_task)
        tasks = scheduler.list_tasks()
        assert len(tasks) >= 2

    @pytest.mark.asyncio
    async def test_user_quota(self, scheduler):
        """Test user quota enforcement."""
        scheduler.set_user_quota("quota_user", max_tasks=2, max_gpu_hours=1)

        def dummy():
            return 1

        for i in range(2):
            task = Task(func=dummy, user_id="quota_user")
            await scheduler.submit_task(task)

        task = Task(func=dummy, user_id="quota_user")
        with pytest.raises(RuntimeError):
            await scheduler.submit_task(task)

    @pytest.mark.asyncio
    async def test_get_stats(self, scheduler, sample_task):
        """Test queue statistics."""
        await scheduler.submit_task(sample_task)
        stats = scheduler.get_stats()
        assert stats.total_tasks >= 1
