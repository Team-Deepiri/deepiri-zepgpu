"""Versioned training workload specification for containerized runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deepiri_zepgpu.training.config import filter_secrets

_FORBIDDEN_MOUNT_NAMES = {"docker.sock", "containerd.sock"}


class TrainingWorkloadSpec(BaseModel):
    """Safe training workload/container contract (Phase 17.1)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    image: str = Field(min_length=1, max_length=512)
    command: list[str] = Field(
        default_factory=lambda: ["python", "-m", "deepiri_zepgpu.training.cli"]
    )
    gpu_devices: list[int] = Field(default_factory=lambda: [0])
    environment: dict[str, str] = Field(default_factory=dict)
    model_ref: str | None = None
    dataset_ref: str | None = None
    timeout_seconds: int = Field(default=3600, ge=30, le=86400)
    memory_limit_mb: int = Field(default=8192, ge=256)
    cpu_limit: float = Field(default=4.0, gt=0)
    network_enabled: bool = True
    privileged: bool = False
    read_only_rootfs: bool = True
    # host:ip or host:host-gateway pairs passed as docker --add-host
    extra_hosts: list[str] = Field(default_factory=list)
    # Optional docker --user value, e.g. "1000:1000". Prefer host uid:gid for
    # bind mounts instead of world-writable chmod workarounds.
    user: str | None = Field(default=None, max_length=64)
    work_dir: Path = Path("/workspace/run")
    checkpoint_mount: Path = Path("/workspace/checkpoints")
    artifact_mount: Path = Path("/workspace/artifacts")
    log_mount: Path = Path("/workspace/logs")
    host_work_dir: Path | None = None
    host_checkpoint_dir: Path | None = None
    host_artifact_dir: Path | None = None
    host_log_dir: Path | None = None
    # When set, all host mounts must resolve under this directory.
    mount_root: Path | None = None

    @model_validator(mode="after")
    def validate_security(self) -> TrainingWorkloadSpec:
        if self.privileged:
            raise ValueError("privileged training containers are not allowed")
        if not self.command:
            raise ValueError("command cannot be empty")
        if self.user is not None:
            cleaned = self.user.strip()
            # docker --user accepts uid, uid:gid, or user names; reject flags / blanks.
            if not cleaned or cleaned.startswith("-") or any(ch.isspace() for ch in cleaned):
                raise ValueError("user must be a docker --user spec like uid:gid")
            if ":" in cleaned:
                left, right = cleaned.split(":", 1)
                if not left or not right or "/" in cleaned:
                    raise ValueError("user must be a docker --user spec like uid:gid")
            self.user = cleaned
        host_mounts = (
            self.host_work_dir,
            self.host_checkpoint_dir,
            self.host_artifact_dir,
            self.host_log_dir,
        )
        if any(host is not None for host in host_mounts) and self.user is None:
            raise ValueError("user (docker --user) is required when host mounts are set")
        for host in host_mounts:
            if host is not None:
                self._assert_safe_host_mount(host)
        return self

    def _assert_safe_host_mount(self, host: Path) -> None:
        resolved = host.expanduser().resolve()

        # Reject filesystem roots on every platform, including C:\ on Windows.
        if resolved == Path(resolved.anchor):
            raise ValueError(f"host mount path is forbidden: {resolved}")

        forbidden_exact_paths = {
            Path("/etc").resolve(),
            Path("/root").resolve(),
        }
        if resolved in forbidden_exact_paths:
            raise ValueError(f"host mount path is forbidden: {resolved}")

        if resolved.name in _FORBIDDEN_MOUNT_NAMES:
            raise ValueError(f"host mount path is forbidden: {resolved}")

        sensitive_parents = (
            Path("/etc").resolve(),
            Path("/root").resolve(),
            Path("/var/run").resolve(),
            Path("/run").resolve(),
        )
        if (
            any(resolved == prefix or prefix in resolved.parents for prefix in sensitive_parents)
            and self.mount_root is None
        ):
            raise ValueError(f"host mount path is forbidden without mount_root: {resolved}")

        if self.mount_root is not None:
            root = self.mount_root.expanduser().resolve()
            if root == Path(root.anchor):
                raise ValueError(f"mount_root cannot be a filesystem root: {root}")
            if resolved != root and root not in resolved.parents:
                raise ValueError(f"host mount {resolved} escapes mount_root jail {root}")

    def filtered_environment(self) -> dict[str, str]:
        filtered = filter_secrets(dict(self.environment))
        return {
            str(key): str(value) for key, value in filtered.items() if str(value) != "[REDACTED]"
        }

    def mount_map(self) -> dict[str, str]:
        """Return container_path -> host_path for declared mounts only."""
        return {container: host for container, host, _mode in self.mount_entries()}

    def mount_entries(self) -> list[tuple[str, str, str]]:
        """Return (container_path, host_path, mode) for declared mounts."""
        mapping: list[tuple[str, str, str]] = []
        pairs = [
            (self.work_dir, self.host_work_dir, "rw"),
            (self.checkpoint_mount, self.host_checkpoint_dir, "rw"),
            (self.artifact_mount, self.host_artifact_dir, "rw"),
            (self.log_mount, self.host_log_dir, "rw"),
        ]
        for container, host, mode in pairs:
            if host is not None:
                self._assert_safe_host_mount(host)
                mapping.append((str(container), str(host.expanduser().resolve()), mode))
        return mapping

    def to_public_dict(self) -> dict[str, Any]:
        filtered = filter_secrets(self.model_dump(mode="json"))
        assert isinstance(filtered, dict)
        return filtered
