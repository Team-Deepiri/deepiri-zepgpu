"""Provider-side Phase 18 launch message router and process supervisor."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import stat
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from deepiri_zepgpu.config import settings
from deepiri_zepgpu.training.config import DistributedStrategy, TrainingRunConfig
from deepiri_zepgpu.training.runtime import RuntimeHandle, TrainingRuntime
from deepiri_zepgpu.training.worker_identity import persist_worker_identity
from deepiri_zepgpu.training.workload import TrainingWorkloadSpec

logger = logging.getLogger(__name__)


class TrainingAgentRunner:
    """Launch only coordinator-authenticated messages received on provider WSS."""

    def __init__(self, *, provider_token: str, runtime: TrainingRuntime | None = None) -> None:
        self.provider_token = provider_token
        self.runtime = runtime or TrainingRuntime(allow_missing_allowlist=True)
        self._handles: dict[str, list[RuntimeHandle]] = {}
        self._work_dirs: dict[str, Path] = {}
        self._watchers: set[asyncio.Task[None]] = set()
        self._cancelled_runs: set[str] = set()
        self._credential_refreshers: dict[str, asyncio.Task[None]] = {}
        self._credential_paths: dict[str, list[Path]] = {}

    async def handle_message(self, message: dict[str, Any]) -> bool:
        message_type = message.get("type")
        if message_type == "training_launch":
            await self.launch(message)
            return True
        if message_type == "training_cancel":
            await self.cancel(str(message.get("run_id") or ""))
            return True
        return False

    async def launch(self, message: dict[str, Any]) -> None:
        run_id = str(message.get("run_id") or "")
        worker_id = str(message.get("worker_id") or "")
        peer_id = str(message.get("provider_id") or "")
        room_id = str(message.get("room_id") or "")
        credential = str(message.get("credential") or "")
        base_url = str(message.get("base_url") or "").rstrip("/")
        config = TrainingRunConfig.model_validate(message.get("config"))
        if (
            not run_id
            or not worker_id
            or not peer_id
            or not room_id
            or not credential
            or not base_url
            or config.schema_version != 3
            or config.phase18 is None
        ):
            raise ValueError("invalid Phase 18 provider launch message")
        if run_id in self._handles:
            return
        processes = message.get("processes")
        if not isinstance(processes, list) or not processes:
            raise ValueError("Phase 18 launch has no process rank assignments")
        if config.phase18.strategy == DistributedStrategy.DILOCO:
            processes = processes[:1]

        root = Path(tempfile.mkdtemp(prefix=f"zepgpu-phase18-{run_id[:8]}-"))
        handles: list[RuntimeHandle] = []
        credential_paths: list[Path] = []
        try:
            for index, process in enumerate(processes):
                if not isinstance(process, dict):
                    raise ValueError("invalid Phase 18 process assignment")
                process_dir = root / f"process-{index}"
                process_dir.mkdir(parents=True)
                identity = {
                    "run_id": run_id,
                    "room_id": room_id,
                    "worker_id": worker_id,
                    "peer_id": peer_id,
                    "process": process,
                    "rendezvous": message.get("rendezvous"),
                    "transport_mode": message.get("transport_mode") or "dialout",
                    "vpn_ip": message.get("vpn_ip"),
                    "data_plane_secret": message.get("data_plane_secret"),
                    "room_mac_key": message.get("room_mac_key"),
                    "peer_worker_id": message.get("peer_worker_id"),
                    "peer_worker_ids": message.get("peer_worker_ids") or [],
                    "overlay_backend": message.get("overlay_backend") or "iroh",
                    "data_plane_listen_host": message.get("vpn_ip") or "0.0.0.0",
                }
                persist_worker_identity(process_dir, identity)
                (process_dir / "config.json").write_text(
                    json.dumps(config.to_public_dict(), sort_keys=True), encoding="utf-8"
                )
                credential_path = process_dir / "run.cred"
                credential_path.write_text(credential, encoding="utf-8")
                credential_paths.append(credential_path)
                token_path = process_dir / "provider.token"
                token_path.write_text(self.provider_token, encoding="utf-8")
                for secret_path in (credential_path, token_path):
                    secret_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
                assignment_devices = [int(process["device_index"])]
                spec = TrainingWorkloadSpec(
                    image=settings.training_image,
                    command=[
                        sys.executable,
                        "-m",
                        "deepiri_zepgpu.training.process_worker",
                        "--work-dir",
                        str(process_dir),
                        "--base-url",
                        base_url,
                    ],
                    gpu_devices=assignment_devices,
                    timeout_seconds=config.phase18.maximum_runtime_seconds,
                    memory_limit_mb=config.distributed.runtime.memory_limit_mb,
                    cpu_limit=config.distributed.runtime.cpu_limit,
                    privileged=False,
                )
                handle = await self.runtime.start_process(spec)
                handles.append(handle)
            self._handles[run_id] = handles
            self._work_dirs[run_id] = root

            self._credential_paths[run_id] = credential_paths

            refresh_task = asyncio.create_task(
                self._refresh_run_credential_loop(
                    run_id=run_id,
                    worker_id=worker_id,
                    peer_id=peer_id,
                    base_url=base_url,
                    credential_paths=credential_paths,
                )
            )
            self._credential_refreshers[run_id] = refresh_task

            watcher = asyncio.create_task(
                self._watch(
                    run_id=run_id,
                    worker_id=worker_id,
                    peer_id=peer_id,
                    base_url=base_url,
                    handles=handles,
                )
            )
            self._watchers.add(watcher)
            watcher.add_done_callback(self._watchers.discard)

        except Exception as exc:
            logger.exception(
                "Failed to launch training worker %s for run %s: %s",
                worker_id,
                run_id,
                exc,
            )
            for handle in handles:
                await self.runtime.cleanup(handle)
            shutil.rmtree(root, ignore_errors=True)
            raise

    async def _watch(
        self,
        *,
        run_id: str,
        worker_id: str,
        peer_id: str,
        base_url: str,
        handles: list[RuntimeHandle],
    ) -> None:
        try:
            return_codes = await asyncio.gather(
                *(self.runtime.wait(handle) for handle in handles), return_exceptions=True
            )
            failure = next(
                (value for value in return_codes if isinstance(value, BaseException) or value != 0),
                None,
            )
            if failure is not None and run_id not in self._cancelled_runs:
                await self._report_failure(
                    run_id=run_id,
                    worker_id=worker_id,
                    peer_id=peer_id,
                    base_url=base_url,
                    error=f"provider process failed: {failure}",
                )
        finally:
            await self._cleanup(run_id)

    async def _report_failure(
        self,
        *,
        run_id: str,
        worker_id: str,
        peer_id: str,
        base_url: str,
        error: str,
    ) -> None:
        # The provider supervisor observes process termination but does not own
        # authoritative outer-round state. Do not guess a round number here;
        # the coordinator/database provide the correct round context.
        payload = {
            "event_id": str(uuid.uuid4()),
            "kind": "round_failed",
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": {
                "error_type": error[:255],
                "error": error,
                "source": "provider_process_supervisor",
            },
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{base_url}/api/v1/training-runs/{run_id}/workers/{worker_id}/events",
                    params={"peer_id": peer_id},
                    headers={"Authorization": f"Bearer {self.provider_token}"},
                    json=payload,
                )
        except Exception:
            logger.exception("Failed to report Phase 18 provider process failure")

    async def cancel(self, run_id: str) -> None:
        if run_id:
            self._cancelled_runs.add(run_id)
            await self._cleanup(run_id)

    async def _cleanup(self, run_id: str) -> None:
        refresh_task = self._credential_refreshers.pop(run_id, None)
        if refresh_task is not None and refresh_task is not asyncio.current_task():
            refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresh_task
        self._credential_paths.pop(run_id, None)

        handles = self._handles.pop(run_id, [])
        for handle in handles:
            await self.runtime.cleanup(handle)
        root = self._work_dirs.pop(run_id, None)
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    async def close(self) -> None:
        for run_id in list(self._handles):
            self._cancelled_runs.add(run_id)
            await self._cleanup(run_id)

    async def _refresh_run_credential_loop(
        self,
        *,
        run_id: str,
        worker_id: str,
        peer_id: str,
        base_url: str,
        credential_paths: list[Path],
    ) -> None:
        # Run credentials are currently valid for 15 minutes. Refresh after ten
        # minutes, leaving a five-minute safety margin. If refresh fails, retry
        # quickly instead of waiting another full ten minutes.
        delay_seconds = 600.0
        while run_id not in self._cancelled_runs:
            await asyncio.sleep(delay_seconds)

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        f"{base_url}/api/v1/training-runs/"
                        f"{run_id}/workers/{worker_id}/credential",
                        params={"peer_id": peer_id},
                        headers={"Authorization": f"Bearer {self.provider_token}"},
                    )

                if response.status_code in {404, 409}:
                    # The run/worker is gone or terminal; no more refreshes are needed.
                    return

                response.raise_for_status()
                body = response.json()
                new_credential = str(body.get("credential") or "").strip()
                if not new_credential:
                    raise RuntimeError("credential refresh response did not include a credential")

                # Every local rank for one TrainingWorker must receive the exact same
                # refreshed token. Atomic replace prevents readers from seeing a
                # partially-written credential.
                for path in credential_paths:
                    temporary = path.with_name(f"{path.name}.tmp")
                    temporary.write_text(new_credential, encoding="utf-8")
                    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
                    temporary.replace(path)

                delay_seconds = 600.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Failed to refresh Phase 18 run credential for %s; retrying shortly",
                    run_id,
                )
                delay_seconds = 30.0
