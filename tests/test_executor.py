"""Tests for executor module."""

import asyncio
import pytest

from deepiri_zepgpu.core.executor import TaskExecutor
from deepiri_zepgpu.core.gpu_manager import GPUManager
from deepiri_zepgpu.core.task import Task, TaskResources


@pytest.fixture
async def gpu_manager():
    """Create a test GPU manager."""
    manager = GPUManager(enable_nvml=False)
    await manager.initialize()
    yield manager
    manager.shutdown()


@pytest.fixture
def executor(gpu_manager):
    """Create a test executor."""
    return TaskExecutor(gpu_manager)


@pytest.fixture
def sample_task():
    """Create a sample task."""
    def dummy_func():
        return 42
    return Task(
        func=dummy_func,
        resources=TaskResources(gpu_memory_mb=1024),
        gpu_device_id=0,
    )


class TestTaskExecutor:
    """Test cases for TaskExecutor."""

    @pytest.mark.asyncio
    async def test_execute_simple_task(self, executor, sample_task):
        """Test executing a simple task."""
        result = await executor.execute_task(sample_task)
        assert result.success is True
        assert result.result == 42

    @pytest.mark.asyncio
    async def test_execute_task_with_args(self, executor):
        """Test executing task with arguments."""
        def add_func(a, b):
            return a + b

        task = Task(
            func=add_func,
            args=(2, 3),
            resources=TaskResources(),
            gpu_device_id=0,
        )
        result = await executor.execute_task(task)
        assert result.success is True
        assert result.result == 5

    @pytest.mark.asyncio
    async def test_execute_task_with_kwargs(self, executor):
        """Test executing task with keyword arguments."""
        def multiply_func(a, b=2):
            return a * b

        task = Task(
            func=multiply_func,
            kwargs={"a": 3, "b": 4},
            resources=TaskResources(),
            gpu_device_id=0,
        )
        result = await executor.execute_task(task)
        assert result.success is True
        assert result.result == 12

    @pytest.mark.asyncio
    async def test_execute_failing_task(self, executor):
        """Test executing a failing task."""
        def failing_func():
            raise ValueError("Test error")

        task = Task(
            func=failing_func,
            resources=TaskResources(),
            gpu_device_id=0,
        )
        result = await executor.execute_task(task)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_batch(self, executor):
        """Test batch execution."""
        def increment(x):
            return x + 1

        tasks = [
            Task(func=increment, args=(i,), resources=TaskResources(), gpu_device_id=0)
            for i in range(5)
        ]
        results = await executor.execute_batch(tasks)
        assert len(results) == 5
        assert all(r.success for r in results)
        assert [r.result for r in results] == [1, 2, 3, 4, 5]
