"""Task executor with container isolation and resource limits."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from deepiri_zepgpu.core.task import Task, TaskResult, TaskStatus
from deepiri_zepgpu.core.gpu_manager import GPUManager, GPUDevice


@dataclass
class ExecutionResult:
    """Result from task execution."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    execution_time: float = 0.0
    gpu_memory_used_mb: float = 0.0


class TaskExecutor:
    """Executes GPU tasks with container isolation."""

    def __init__(
        self,
        gpu_manager: GPUManager,
        container_runtime: str = "docker",
        enable_isolation: bool = True,
        work_dir: Optional[str] = None,
    ):
        self._gpu_manager = gpu_manager
        self._container_runtime = container_runtime
        self._enable_isolation = enable_isolation
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="deepiri_gpu_")

        self._running_executors: dict[str, asyncio.Task] = {}
        self._container_ids: dict[str, str] = {}
        self._lock = threading.RLock()

    async def execute_task(
        self,
        task: Task,
        on_progress: Optional[Callable[[str, float], None]] = None,
    ) -> ExecutionResult:
        """Execute a single task on allocated GPU."""
        start_time = time.time()
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()

        gpu_device = self._gpu_manager.get_device(task.gpu_device_id or 0)

        try:
            result = await self._run_task(
                task=task,
                gpu_device=gpu_device,
                on_progress=on_progress,
            )
            execution_time = time.time() - start_time
            task.status = TaskStatus.COMPLETED
            task.result = result

            return ExecutionResult(
                success=True,
                result=result,
                execution_time=execution_time,
                gpu_memory_used_mb=gpu_device.available_memory_mb if gpu_device else 0,
            )

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            raise

        except Exception as e:
            execution_time = time.time() - start_time
            import traceback
            tb = traceback.format_exc()
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.traceback = tb

            return ExecutionResult(
                success=False,
                error=str(e),
                traceback=tb,
                execution_time=execution_time,
            )

        finally:
            task.completed_at = datetime.utcnow()

    async def _run_task(
        self,
        task: Task,
        gpu_device: Optional[GPUDevice],
        on_progress: Optional[Callable[[str, float], None]] = None,
    ) -> Any:
        """Run the actual task logic."""
        func = task.func
        args = task.args
        kwargs = task.kwargs

        if asyncio.iscoroutinefunction(func):
            result = await func(*args, **kwargs)
        else:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: func(*args, **kwargs)
            )

        return result

    async def execute_in_container(
        self,
        task: Task,
        image: str = "deepiri-gpu:latest",
    ) -> ExecutionResult:
        """Execute task in isolated Docker container."""
        container_id = None
        try:
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = str(task.gpu_device_id or 0)

            docker_cmd = [
                self._container_runtime, "run",
                "--rm",
                "--gpus", f'"device={task.gpu_device_id or 0}"',
                "-e", f"TASK_ID={task.task_id}",
                "-e", f"CUDA_VISIBLE_DEVICES={task.gpu_device_id or 0}",
                "--memory", f"{task.resources.gpu_memory_mb}m",
                "--cpus", str(task.resources.cpu_cores),
                "-v", f"{self._work_dir}:/workspace",
                "-w", "/workspace",
                image,
                "python", "-c", self._generate_task_code(task),
            ]

            process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            container_id = f"deepiri_{task.task_id[:8]}"
            self._container_ids[task.task_id] = container_id

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=task.resources.timeout_seconds,
            )

            if process.returncode != 0:
                raise RuntimeError(f"Container execution failed: {stderr.decode()}")

            return ExecutionResult(
                success=True,
                result=stdout.decode(),
                execution_time=0.0,
            )

        except asyncio.TimeoutError:
            await self._kill_container(container_id)
            raise TimeoutError(f"Task {task.task_id} timed out after {task.resources.timeout_seconds}s")

        except Exception as e:
            import traceback
            return ExecutionResult(
                success=False,
                error=str(e),
                traceback=traceback.format_exc(),
            )

        finally:
            if container_id:
                await self._cleanup_container(container_id)

    def _generate_task_code(self, task: Task) -> str:
        """Generate Python code to execute task in container."""
        import base64
        import pickle

        serialized_func = base64.b64encode(pickle.dumps(task.func)).decode()
        serialized_args = base64.b64encode(pickle.dumps(task.args)).decode()
        serialized_kwargs = base64.b64encode(pickle.dumps(task.kwargs)).decode()

        code = f"""
import base64
import pickle
import sys

func = pickle.loads(base64.b64decode('{serialized_func}'))
args = pickle.loads(base64.b64decode('{serialized_args}'))
kwargs = pickle.loads(base64.b64decode('{serialized_kwargs}'))

try:
    result = func(*args, **kwargs)
    output = pickle.dumps(result)
    sys.stdout.buffer.write(base64.b64encode(output))
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
"""
        return code

    async def _kill_container(self, container_id: Optional[str]) -> None:
        """Kill a running container."""
        if container_id:
            try:
                await asyncio.create_subprocess_exec(
                    self._container_runtime, "kill", container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except Exception:
                pass

    async def _cleanup_container(self, container_id: str) -> None:
        """Clean up container resources."""
        try:
            await asyncio.create_subprocess_exec(
                self._container_runtime, "rm", "-f", container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception:
            pass
        self._container_ids.pop(container_id, None)

    async def execute_batch(
        self,
        tasks: list[Task],
        batch_size: int = 4,
    ) -> list[ExecutionResult]:
        """Execute multiple tasks in parallel with batching."""
        results = []
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_results = await asyncio.gather(
                *[self.execute_task(task) for task in batch],
                return_exceptions=True,
            )
            for result in batch_results:
                if isinstance(result, Exception):
                    results.append(ExecutionResult(success=False, error=str(result)))
                else:
                    results.append(result)
        return results

    def get_active_executors(self) -> list[str]:
        """Get list of active executor task IDs."""
        return list(self._running_executors.keys())

    def cleanup(self) -> None:
        """Cleanup executor resources."""
        for task_id in list(self._running_executors.keys()):
            self.cancel_task(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        executor_task = self._running_executors.get(task_id)
        if executor_task:
            executor_task.cancel()
            container_id = self._container_ids.pop(task_id, None)
            if container_id:
                asyncio.create_task(self._cleanup_container(container_id))
            return True
        return False
