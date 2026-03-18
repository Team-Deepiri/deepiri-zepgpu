"""Sandboxed container execution for task isolation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Optional

from deepiri_zepgpu.core.task import Task


@dataclass
class ContainerConfig:
    """Container configuration for task isolation."""
    image: str = "deepiri-gpu:latest"
    memory_limit_mb: int = 4096
    cpu_limit: float = 2.0
    gpu_devices: list[int] | None = None
    network_enabled: bool = False
    read_only_rootfs: bool = True
    tmpfs_mounts: list[str] | None = None
    environment_vars: dict[str, str] | None = None


class ContainerSandbox:
    """Manages containerized task execution for isolation."""

    def __init__(
        self,
        runtime: str = "docker",
        default_config: Optional[ContainerConfig] = None,
    ):
        self._runtime = runtime
        self._default_config = default_config or ContainerConfig()
        self._running_containers: dict[str, str] = {}
        self._lock = threading.Lock()

    def get_container_config(self, task: Task) -> ContainerConfig:
        """Get container configuration for a task."""
        config = ContainerConfig(
            memory_limit_mb=task.resources.gpu_memory_mb,
            cpu_limit=task.resources.cpu_cores,
            gpu_devices=[task.gpu_device_id] if task.gpu_device_id is not None else None,
        )
        return config

    def build_command(self, config: ContainerConfig, task: Task) -> list[str]:
        """Build Docker command for task execution."""
        cmd = [self._runtime, "run", "--rm"]

        cmd.extend(["--memory", f"{config.memory_limit_mb}m"])
        cmd.extend(["--cpus", str(config.cpu_limit)])

        if config.gpu_devices is not None:
            for device in config.gpu_devices:
                cmd.extend(["--gpus", f'"device={device}"'])

        if not config.network_enabled:
            cmd.append("--network=none")

        if config.read_only_rootfs:
            cmd.append("--read-only")

        if config.tmpfs_mounts:
            for mount in config.tmpfs_mounts:
                cmd.extend(["--tmpfs", mount])

        if config.environment_vars:
            for key, value in config.environment_vars.items():
                cmd.extend(["-e", f"{key}={value}"])

        cmd.extend(["-e", f"TASK_ID={task.task_id}"])
        cmd.extend(["-e", f"CUDA_VISIBLE_DEVICES={task.gpu_device_id or 0}"])

        cmd.append(config.image)
        cmd.extend(["python", "-m", "deepiri_zepgpu.execute", task.task_id])

        return cmd

    async def execute(
        self,
        task: Task,
        config: Optional[ContainerConfig] = None,
    ) -> tuple[int, str, str]:
        """Execute task in isolated container."""
        config = config or self.get_container_config(task)
        cmd = self.build_command(config, task)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_environment(config),
        )

        container_id = f"deepiri_{task.task_id[:8]}"
        with self._lock:
            self._running_containers[task.task_id] = container_id

        stdout, stderr = await process.communicate()

        with self._lock:
            self._running_containers.pop(task.task_id, None)

        return process.returncode, stdout.decode(), stderr.decode()

    def _build_environment(self, config: ContainerConfig) -> dict[str, str]:
        """Build environment variables for container."""
        env = os.environ.copy()
        env["DEEPIRI_RUNTIME"] = "container"
        if config.environment_vars:
            env.update(config.environment_vars)
        return env

    async def stop_container(self, task_id: str) -> bool:
        """Stop a running container."""
        with self._lock:
            container_id = self._running_containers.get(task_id)

        if not container_id:
            return False

        try:
            result = await asyncio.create_subprocess_exec(
                self._runtime, "stop", container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await result.wait()
            with self._lock:
                self._running_containers.pop(task_id, None)
            return True
        except Exception:
            return False

    def list_containers(self) -> dict[str, str]:
        """List running DeepIRI containers."""
        return dict(self._running_containers)

    async def cleanup_all(self) -> None:
        """Cleanup all running containers."""
        task_ids = list(self._running_containers.keys())
        for task_id in task_ids:
            await self.stop_container(task_id)


class SeccompProfile:
    """Seccomp profile for syscall filtering."""

    DEFAULT_ALLOW_LIST = [
        "read", "write", "close", "stat", "fstat", "mmap",
        "mprotect", "munmap", "brk", "rt_sigaction", "rt_sigreturn",
        "ioctl", "readlink", "sysinfo", "getdents64", "getrandom",
        "clock_gettime", "exit_group",
    ]

    def __init__(self, allow_syscalls: list[str] | None = None):
        self._allow_syscalls = allow_syscalls or self.DEFAULT_ALLOW_LIST

    def to_json(self) -> str:
        """Generate seccomp profile as JSON."""
        import json
        return json.dumps({
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"],
            "syscalls": [
                {
                    "names": self._allow_syscalls,
                    "action": "SCMP_ACT_ALLOW",
                }
            ],
        }, indent=2)
