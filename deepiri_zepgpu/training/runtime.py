"""Docker and process runtimes for Phase 17 training workloads."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from deepiri_zepgpu.training.image_trust import (
    DEFAULT_ALLOWLIST_PATH,
    ImageTrustPolicy,
)
from deepiri_zepgpu.training.workload import TrainingWorkloadSpec


class TrainingRuntimeError(RuntimeError):
    pass


@dataclass
class RuntimeHandle:
    runtime_id: str
    mode: str
    container_name: str | None = None
    work_dir: Path | None = None
    process: asyncio.subprocess.Process | None = None
    ephemeral_dirs: list[Path] = field(default_factory=list)
    timeout_seconds: int | None = None


class TrainingRuntime:
    """Launch and clean up training workers in process or Docker mode."""

    def __init__(
        self,
        *,
        docker_bin: str = "docker",
        trust_policy: ImageTrustPolicy | None = None,
        allowlist_path: Path | None = None,
        allow_missing_allowlist: bool | None = None,
    ) -> None:
        self.docker_bin = docker_bin
        path = allowlist_path or DEFAULT_ALLOWLIST_PATH
        if trust_policy is not None:
            self.trust_policy = trust_policy
        elif path.exists():
            self.trust_policy = ImageTrustPolicy.from_file(path)
        else:
            # Fail closed outside explicit local/dev override.
            allow_missing = (
                allow_missing_allowlist
                if allow_missing_allowlist is not None
                else os.getenv("ZEPGPU_TRAINING_DEV", "").strip() in {"1", "true", "yes"}
            )
            if not allow_missing:
                raise TrainingRuntimeError(
                    f"training image allowlist missing at {path}; "
                    "refusing to start (set ZEPGPU_TRAINING_DEV=1 only for local experiments)"
                )
            self.trust_policy = ImageTrustPolicy({"zepgpu-training:local"})
        self._handles: dict[str, RuntimeHandle] = {}

    def build_docker_command(self, spec: TrainingWorkloadSpec, *, name: str) -> list[str]:
        if spec.privileged:
            raise TrainingRuntimeError("privileged containers are disabled")
        self.trust_policy.assert_trusted(spec.image)
        cmd = [
            self.docker_bin,
            "run",
            "--detach",
            "--name",
            name,
            "--security-opt",
            "no-new-privileges",
            "--memory",
            f"{spec.memory_limit_mb}m",
            "--cpus",
            str(spec.cpu_limit),
        ]
        # Explicitly never pass --privileged.
        if spec.read_only_rootfs:
            cmd.append("--read-only")
            cmd.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=512m"])
        if not spec.network_enabled:
            cmd.append("--network=none")
        for host_mapping in spec.extra_hosts:
            cmd.extend(["--add-host", host_mapping])
        if spec.gpu_devices:
            # Single --gpus device=... list; remapped visibility inside the container.
            devices = ",".join(str(device) for device in spec.gpu_devices)
            cmd.extend(["--gpus", f"device={devices}"])
            cmd.extend(["-e", f"NVIDIA_VISIBLE_DEVICES={devices}"])
        for key, value in spec.filtered_environment().items():
            cmd.extend(["-e", f"{key}={value}"])
        for container_path, host_path, mode in spec.mount_entries():
            cmd.extend(["-v", f"{host_path}:{container_path}:{mode}"])
        # Replace image ENTRYPOINT so the full command list is authoritative.
        cmd.extend(["--entrypoint", ""])
        cmd.append(spec.image)
        cmd.extend(spec.command)
        return cmd

    async def start_docker(self, spec: TrainingWorkloadSpec) -> RuntimeHandle:
        runtime_id = str(uuid.uuid4())
        name = f"zepgpu-train-{runtime_id[:8]}"
        work = Path(tempfile.mkdtemp(prefix=f"zepgpu-train-{runtime_id[:8]}-"))
        if spec.host_work_dir is None:
            spec = spec.model_copy(update={"host_work_dir": work})
        cmd = self.build_docker_command(spec, name=name)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            shutil.rmtree(work, ignore_errors=True)
            raise TrainingRuntimeError(
                f"docker run failed ({process.returncode}): {stderr.decode('utf-8', 'replace')}"
            )
        handle = RuntimeHandle(
            runtime_id=runtime_id,
            mode="docker",
            container_name=name,
            work_dir=work,
            ephemeral_dirs=[work],
            timeout_seconds=spec.timeout_seconds,
        )
        self._handles[runtime_id] = handle
        return handle

    async def start_process(
        self, spec: TrainingWorkloadSpec, *, env: dict[str, str] | None = None
    ) -> RuntimeHandle:
        runtime_id = str(uuid.uuid4())
        work = Path(tempfile.mkdtemp(prefix=f"zepgpu-proc-{runtime_id[:8]}-"))
        process_env = os.environ.copy()
        process_env.update(spec.filtered_environment())
        if env:
            process_env.update(env)
        process = await asyncio.create_subprocess_exec(
            *spec.command,
            cwd=str(work),
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        handle = RuntimeHandle(
            runtime_id=runtime_id,
            mode="process",
            work_dir=work,
            process=process,
            ephemeral_dirs=[work],
            timeout_seconds=spec.timeout_seconds,
        )
        self._handles[runtime_id] = handle
        return handle

    async def wait(self, handle: RuntimeHandle, *, timeout_seconds: float | None = None) -> int:
        """Block until the workload exits; enforce timeout and cleanup on expiry."""
        deadline = timeout_seconds
        if deadline is None:
            deadline = float(handle.timeout_seconds or 3600)
        try:
            if handle.mode == "process" and handle.process is not None:
                return await asyncio.wait_for(handle.process.wait(), timeout=deadline)
            if handle.mode == "docker" and handle.container_name:
                wait = await asyncio.create_subprocess_exec(
                    self.docker_bin,
                    "wait",
                    handle.container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _stderr = await asyncio.wait_for(wait.communicate(), timeout=deadline)
                if wait.returncode != 0:
                    raise TrainingRuntimeError("docker wait failed")
                return int(stdout.decode("utf-8").strip() or "0")
        except TimeoutError as exc:
            await self.cleanup(handle)
            raise TrainingRuntimeError(f"training runtime exceeded timeout of {deadline}s") from exc
        raise TrainingRuntimeError(f"cannot wait on runtime mode {handle.mode}")

    async def stop(self, handle: RuntimeHandle, *, timeout_seconds: float = 15.0) -> None:
        if handle.mode == "docker" and handle.container_name:
            stop = await asyncio.create_subprocess_exec(
                self.docker_bin,
                "rm",
                "-f",
                handle.container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=timeout_seconds)
            except TimeoutError:
                stop.kill()
        if handle.process is not None and handle.process.returncode is None:
            handle.process.terminate()
            try:
                await asyncio.wait_for(handle.process.wait(), timeout=timeout_seconds)
            except TimeoutError:
                handle.process.kill()
                await handle.process.wait()

    async def cleanup(self, handle: RuntimeHandle) -> None:
        await self.stop(handle)
        for path in handle.ephemeral_dirs:
            shutil.rmtree(path, ignore_errors=True)
        self._handles.pop(handle.runtime_id, None)

    async def cleanup_all(self) -> None:
        for handle in list(self._handles.values()):
            await self.cleanup(handle)

    async def inspect_privileged(self, handle: RuntimeHandle) -> bool | None:
        if handle.mode != "docker" or not handle.container_name:
            return None
        proc = await asyncio.create_subprocess_exec(
            self.docker_bin,
            "inspect",
            "--format",
            "{{json .HostConfig.Privileged}}",
            handle.container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await proc.communicate()
        if proc.returncode != 0:
            return None
        return json.loads(stdout.decode("utf-8")) is True

    def list_active(self) -> list[RuntimeHandle]:
        return list(self._handles.values())
