"""Tests for executor module."""

import asyncio
from collections.abc import AsyncGenerator

import pytest

from deepiri_zepgpu.core.executor import ExecutionResult, TaskExecutor
from deepiri_zepgpu.core.gpu_manager import GPUManager
from deepiri_zepgpu.core.task import Task, TaskResources


@pytest.fixture
async def gpu_manager() -> AsyncGenerator[GPUManager, None]:
    """Create a test GPU manager."""
    manager = GPUManager(enable_nvml=False)
    await manager.initialize()
    yield manager
    manager.shutdown()


@pytest.fixture
def executor(gpu_manager: GPUManager) -> TaskExecutor:
    """Create a test executor."""
    return TaskExecutor(gpu_manager)


@pytest.fixture
def sample_task() -> Task:
    """Create a sample task."""

    def dummy_func() -> int:
        return 42

    return Task(
        func=dummy_func,
        resources=TaskResources(gpu_memory_mb=1024),
        gpu_device_id=0,
    )


class TestTaskExecutor:
    """Test cases for TaskExecutor."""

    @pytest.mark.asyncio
    async def test_execute_simple_task(self, executor: TaskExecutor, sample_task: Task) -> None:
        """Test executing a simple task."""
        result: ExecutionResult = await executor.execute_task(sample_task)
        assert result.success is True
        assert result.result == 42

    @pytest.mark.asyncio
    async def test_execute_task_with_args(self, executor: TaskExecutor) -> None:
        """Test executing task with arguments."""

        def add_func(a: int, b: int) -> int:
            return a + b

        task = Task(
            func=add_func,
            args=(2, 3),
            resources=TaskResources(),
            gpu_device_id=0,
        )
        result: ExecutionResult = await executor.execute_task(task)
        assert result.success is True
        assert result.result == 5

    @pytest.mark.asyncio
    async def test_execute_task_with_kwargs(self, executor: TaskExecutor) -> None:
        """Test executing task with keyword arguments."""

        def multiply_func(a: int, b: int = 2) -> int:
            return a * b

        task = Task(
            func=multiply_func,
            kwargs={"a": 3, "b": 4},
            resources=TaskResources(),
            gpu_device_id=0,
        )
        result: ExecutionResult = await executor.execute_task(task)
        assert result.success is True
        assert result.result == 12

    @pytest.mark.asyncio
    async def test_execute_failing_task(self, executor: TaskExecutor) -> None:
        """Test executing a failing task."""

        def failing_func() -> None:
            raise ValueError("Test error")

        task = Task(
            func=failing_func,
            resources=TaskResources(),
            gpu_device_id=0,
        )
        result: ExecutionResult = await executor.execute_task(task)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_batch(self, executor: TaskExecutor) -> None:
        """Test batch execution."""

        def increment(x: int) -> int:
            return x + 1

        tasks = [
            Task(func=increment, args=(i,), resources=TaskResources(), gpu_device_id=0)
            for i in range(5)
        ]
        results: list[ExecutionResult] = await executor.execute_batch(tasks)
        assert len(results) == 5
        assert all(r.success for r in results)
        assert [r.result for r in results] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_container_execution_uses_restricted_runtime_flags(
        self,
        executor: TaskExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Executable local SDK tasks must not inherit host network or filesystem access."""
        commands: list[tuple[str, ...]] = []
        subprocess_kwargs: list[dict[str, object]] = []

        class FakeProcess:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"safe", b""

        async def fake_subprocess(*command: str, **kwargs: object) -> FakeProcess:
            commands.append(command)
            subprocess_kwargs.append(kwargs)
            return FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        task = Task(
            func=int,
            args=("42",),
            resources=TaskResources(gpu_memory_mb=8192, container_memory_mb=1536),
            gpu_device_id=3,
        )

        result = await executor.execute_in_container(task, image="trusted-image:tested")

        assert result.success is True
        run_command = commands[0]
        assert run_command[run_command.index("--network") + 1] == "none"
        assert "--read-only" in run_command
        assert run_command[run_command.index("--cap-drop") + 1] == "ALL"
        assert run_command[run_command.index("--security-opt") + 1] == "no-new-privileges"
        assert run_command[run_command.index("--user") + 1] == "65534:65534"
        assert run_command[run_command.index("--pids-limit") + 1] == "256"
        assert run_command[run_command.index("--ulimit") + 1] == "nofile=128:128"
        assert run_command[run_command.index("--gpus") + 1] == "device=3"
        assert '"' not in run_command[run_command.index("--gpus") + 1]
        assert run_command[run_command.index("--memory") + 1] == "1536m"
        assert run_command[run_command.index("--memory") + 1] != "8192m"
        assert "shell" not in subprocess_kwargs[0]
        assert "-v" not in run_command
        assert "--volume" not in run_command

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gpu_device_id", [-1, 1024, "0", "0;id", True, 1.5])
    async def test_container_execution_rejects_invalid_gpu_device_id(
        self,
        executor: TaskExecutor,
        monkeypatch: pytest.MonkeyPatch,
        gpu_device_id: object,
    ) -> None:
        subprocess_called = False

        async def fake_subprocess(*_command: str, **_kwargs: object) -> None:
            nonlocal subprocess_called
            subprocess_called = True

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        task = Task(func=int, gpu_device_id=gpu_device_id)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="gpu_device_id"):
            await executor.execute_in_container(task)
        assert subprocess_called is False

    @pytest.mark.parametrize("container_memory_mb", [0, 63, 262_145, "1024", True])
    def test_container_memory_limit_is_positive_and_bounded(
        self,
        container_memory_mb: object,
    ) -> None:
        with pytest.raises(ValueError, match="container_memory_mb"):
            TaskResources(container_memory_mb=container_memory_mb)  # type: ignore[arg-type]
