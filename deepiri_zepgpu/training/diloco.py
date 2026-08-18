"""Elastic DiLoCo/local-SGD outer synchronization for Phase 18."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from deepiri_zepgpu.training.binary import BinaryEnvelope
from deepiri_zepgpu.training.checkpoint import (
    Phase18CheckpointMetadata,
    make_phase18_checkpoint_metadata,
)
from deepiri_zepgpu.training.compression.base import (
    CompressedUpdate,
    CompressorState,
    UpdateCompressor,
    get_compressor,
    pack_named_arrays,
    unpack_named_arrays,
)
from deepiri_zepgpu.training.config import (
    OuterOptimizerConfig,
    OuterOptimizerKind,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.integrity import (
    FileReplayGuard,
    ReplayGuard,
    envelope_to_neutral,
    sign_live_outer_extensions,
)
from deepiri_zepgpu.training.prom_metrics import record_checkpoint, record_rejoin
from deepiri_zepgpu.training.sync import validate_matching_shapes


class DiLoCoError(RuntimeError):
    pass


class MembershipState(str, Enum):
    ACTIVE = "active"
    BOOTSTRAPPING = "bootstrapping"
    LEFT = "left"
    FAILED = "failed"


class RoundState(str, Enum):
    OPEN = "open"
    PAUSED = "paused"
    FINALIZED = "finalized"


class UpdateDisposition(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    LATE = "late"
    STALE = "stale"
    INACTIVE = "inactive"


@dataclass(slots=True)
class WorkerMembership:
    worker_id: str
    state: MembershipState
    bootstrapped_round: int = 0
    rejoin_count: int = 0
    reason: str | None = None


@dataclass(slots=True)
class UpdateReceipt:
    disposition: UpdateDisposition
    worker_id: str
    round_number: int
    reason: str


@dataclass(slots=True)
class OuterRoundMetric:
    round_number: int
    state: RoundState
    expected_workers: int
    accepted_workers: int
    min_k: int
    straggler_worker_ids: list[str]
    blocked_sync_seconds: float
    uncompressed_bytes: int
    compressed_bytes: int
    compression_ratio: float
    path_type: str = "wan"
    path_class: str = "wan"


@dataclass(slots=True)
class _Round:
    number: int
    deadline_at: datetime
    opened_monotonic: float
    expected_worker_ids: list[str]
    state: RoundState = RoundState.OPEN
    updates: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    transfer_ids: set[str] = field(default_factory=set)
    uncompressed_bytes: int = 0
    compressed_bytes: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)


def _arrays_to_json(values: dict[str, np.ndarray]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "dtype": "float32",
            "shape": list(array.shape),
            "values": np.asarray(array, dtype=np.float32).reshape(-1).tolist(),
        }
        for name, array in sorted(values.items())
    }


def _arrays_from_json(values: dict[str, dict[str, Any]]) -> dict[str, np.ndarray]:
    return {
        name: np.asarray(payload["values"], dtype=np.float32).reshape(payload["shape"])
        for name, payload in sorted(values.items())
    }


class OuterOptimizer:
    """Stateful deterministic SGD/Adam outer optimizer over NumPy tensors."""

    def __init__(self, config: OuterOptimizerConfig) -> None:
        self.config = config
        self.step_count = 0
        self.velocity: dict[str, np.ndarray] = {}
        self.first_moment: dict[str, np.ndarray] = {}
        self.second_moment: dict[str, np.ndarray] = {}

    def apply(
        self, parameters: dict[str, np.ndarray], update: dict[str, np.ndarray]
    ) -> dict[str, np.ndarray]:
        validate_matching_shapes(parameters, update)
        self.step_count += 1
        result: dict[str, np.ndarray] = {}
        for name in sorted(parameters):
            delta = np.asarray(update[name], dtype=np.float32)
            if self.config.kind == OuterOptimizerKind.SGD:
                previous = self.velocity.get(name, np.zeros_like(delta))
                velocity = self.config.momentum * previous + delta
                self.velocity[name] = velocity.astype(np.float32)
                applied = self.config.learning_rate * velocity
            else:
                first = self.first_moment.get(name, np.zeros_like(delta))
                second = self.second_moment.get(name, np.zeros_like(delta))
                first = self.config.beta1 * first + (1 - self.config.beta1) * delta
                second = self.config.beta2 * second + (1 - self.config.beta2) * np.square(delta)
                self.first_moment[name] = first.astype(np.float32)
                self.second_moment[name] = second.astype(np.float32)
                first_hat = first / (1 - self.config.beta1**self.step_count)
                second_hat = second / (1 - self.config.beta2**self.step_count)
                applied = (
                    self.config.learning_rate
                    * first_hat
                    / (np.sqrt(second_hat) + self.config.epsilon)
                )
            result[name] = (parameters[name] + applied).astype(np.float32)
        return result

    def state_dict(self) -> dict[str, Any]:
        return {
            "kind": self.config.kind.value,
            "config": self.config.model_dump(mode="json"),
            "step_count": self.step_count,
            "velocity": _arrays_to_json(self.velocity),
            "first_moment": _arrays_to_json(self.first_moment),
            "second_moment": _arrays_to_json(self.second_moment),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if state.get("kind") != self.config.kind.value:
            raise DiLoCoError("outer optimizer kind does not match checkpoint")
        self.step_count = int(state.get("step_count", 0))
        self.velocity = _arrays_from_json(state.get("velocity", {}))
        self.first_moment = _arrays_from_json(state.get("first_moment", {}))
        self.second_moment = _arrays_from_json(state.get("second_moment", {}))


def encode_state_envelope(
    *,
    room_id: str,
    run_id: str,
    worker_id: str,
    round_number: int,
    state: dict[str, Any],
    payload_type: str = "diloco_global_state",
) -> bytes:
    """Encode a lossless adapter/global state with the versioned binary transport."""

    arrays = {name: np.asarray(value, dtype=np.float32) for name, value in sorted(state.items())}
    if not arrays:
        raise DiLoCoError("state cannot be empty")
    packed = pack_named_arrays(list(arrays), list(arrays.values()), codec="none")
    transfer_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"zepgpu-diloco-state:{run_id}:{round_number}:{worker_id}:{payload_type}",
        )
    )
    return BinaryEnvelope(
        room_id=str(uuid.UUID(room_id)),
        run_id=str(uuid.UUID(run_id)),
        worker_id=str(uuid.UUID(worker_id)),
        transfer_id=transfer_id,
        round=round_number,
        payload_type=payload_type,
        shape=(len(packed.payload),),
        dtype="uint8",
        compression="none",
        payload=packed.payload,
    ).encode()


def decode_state_envelope(
    encoded: bytes,
    *,
    room_id: str,
    run_id: str,
    worker_id: str | None = None,
    round_number: int | None = None,
    payload_types: set[str] | None = None,
) -> tuple[BinaryEnvelope, dict[str, np.ndarray]]:
    envelope = BinaryEnvelope.decode(
        encoded,
        expected_room_id=room_id,
        expected_run_id=run_id,
        expected_worker_id=worker_id,
        expected_round=round_number,
    )
    if envelope.compression != "none":
        raise DiLoCoError("global state envelope must use lossless none compression")
    allowed = payload_types or {"diloco_initial_state", "diloco_global_state"}
    if envelope.payload_type not in allowed:
        raise DiLoCoError("unexpected global state payload type")
    packed = CompressedUpdate(
        codec="none",
        payload=envelope.payload,
        shapes=(),
        dtypes=(),
        names=(),
        uncompressed_bytes=len(envelope.payload),
        compressed_bytes=len(envelope.payload),
    )
    return envelope, {
        name: np.asarray(value, dtype=np.float32)
        for name, value in unpack_named_arrays(packed).items()
    }


def _encode_outer_update(
    *,
    room_id: str,
    run_id: str,
    worker_id: str,
    round_number: int,
    delta: dict[str, Any],
    global_state: dict[str, np.ndarray],
    compressor: UpdateCompressor,
    compressor_state: CompressorState,
    room_mac_key: str | None = None,
) -> bytes:
    """Shared provider/test encoder for the coordinator's sole update format."""

    local = {name: np.asarray(value, dtype=np.float32) for name, value in delta.items()}
    validate_matching_shapes(global_state, local)
    update = compressor.compress(local, compressor_state)
    transfer_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"zepgpu-diloco:{run_id}:{round_number}:{worker_id}",
        )
    )
    extensions = str(update.uncompressed_bytes).encode("ascii")
    envelope = BinaryEnvelope(
        room_id=room_id,
        run_id=run_id,
        worker_id=str(uuid.UUID(worker_id)),
        transfer_id=transfer_id,
        round=round_number,
        payload_type="diloco_outer_delta",
        shape=(len(update.payload),),
        dtype="uint8",
        compression=update.codec,
        payload=update.payload,
        extensions=extensions,
    )
    if room_mac_key:
        envelope = BinaryEnvelope(
            room_id=envelope.room_id,
            run_id=envelope.run_id,
            worker_id=envelope.worker_id,
            transfer_id=envelope.transfer_id,
            round=envelope.round,
            payload_type=envelope.payload_type,
            shape=envelope.shape,
            dtype=envelope.dtype,
            compression=envelope.compression,
            payload=envelope.payload,
            timestamp_ns=envelope.timestamp_ns,
            extensions=sign_live_outer_extensions(
                uncompressed_bytes=update.uncompressed_bytes,
                update=envelope_to_neutral(envelope, room_id=room_id, run_id=run_id),
                room_mac_key=room_mac_key,
            ),
            version=envelope.version,
        )
    return envelope.encode()


class DiLoCoWorkerRuntime:
    """Provider-side H-step/update codec used by the real Phase 18 worker path."""

    def __init__(
        self,
        *,
        room_id: str,
        run_id: str,
        worker_id: str,
        config: TrainingRunConfig,
        initial_state: dict[str, Any],
    ) -> None:
        if config.phase18 is None or config.schema_version != 3:
            raise DiLoCoError("worker runtime requires a schema-version 3 Phase 18 config")
        self.room_id = str(uuid.UUID(room_id))
        self.run_id = str(uuid.UUID(run_id))
        self.worker_id = str(uuid.UUID(worker_id))
        self.config = config
        self.job = config.phase18
        self.global_state = {
            name: np.asarray(value, dtype=np.float32).copy()
            for name, value in sorted(initial_state.items())
        }
        if not self.global_state:
            raise DiLoCoError("initial state cannot be empty")
        self.compressor = get_compressor(config.distributed.compression)
        self.compressor_state = CompressorState()
        self.applied_round = 0
        self.room_mac_key: str | None = None

    def initial_state_envelope(self) -> bytes:
        return encode_state_envelope(
            room_id=self.room_id,
            run_id=self.run_id,
            worker_id=self.worker_id,
            round_number=0,
            state=self.global_state,
            payload_type="diloco_initial_state",
        )

    def encode_update(
        self,
        *,
        round_number: int,
        delta: dict[str, Any],
        completed_local_steps: int,
    ) -> bytes:
        if completed_local_steps <= 0 or completed_local_steps % self.job.diloco_h:
            raise DiLoCoError(
                f"worker has not completed the configured H={self.job.diloco_h} local steps"
            )
        if self.applied_round < round_number - 1:
            raise DiLoCoError("worker must apply the latest global state before this round")
        return _encode_outer_update(
            room_id=self.room_id,
            run_id=self.run_id,
            worker_id=self.worker_id,
            round_number=round_number,
            delta=delta,
            global_state=self.global_state,
            compressor=self.compressor,
            compressor_state=self.compressor_state,
            room_mac_key=self.room_mac_key,
        )

    def apply_global_state(self, encoded: bytes) -> dict[str, np.ndarray]:
        envelope, state = decode_state_envelope(
            encoded,
            room_id=self.room_id,
            run_id=self.run_id,
            worker_id=self.worker_id,
            payload_types={"diloco_global_state"},
        )
        if envelope.round < self.applied_round:
            raise DiLoCoError("cannot apply an older global state")
        validate_matching_shapes(self.global_state, state)
        self.global_state = {name: value.copy() for name, value in state.items()}
        self.applied_round = envelope.round
        self.compressor_state = CompressorState()
        return {name: value.copy() for name, value in self.global_state.items()}


class ElasticDiLoCoCoordinator:
    """Round coordinator with min-k, deadlines, late-update rejection, and rejoin."""

    def __init__(
        self,
        *,
        room_id: str,
        run_id: str,
        config: TrainingRunConfig,
        initial_state: dict[str, Any],
        worker_ids: list[str],
        placement: dict[str, Any] | None = None,
    ) -> None:
        if config.phase18 is None or config.schema_version != 3:
            raise DiLoCoError("elastic DiLoCo requires a schema-version 3 Phase 18 config")
        if len(worker_ids) != len(set(worker_ids)):
            raise DiLoCoError("worker_ids must be unique")
        if len(worker_ids) != config.phase18.requested_node_count:
            raise DiLoCoError("worker_ids must match requested_node_count")
        self.room_id = str(uuid.UUID(room_id))
        self.run_id = str(uuid.UUID(run_id))
        self.config = config
        self.job = config.phase18
        self.global_state = {
            name: np.asarray(value, dtype=np.float32).copy()
            for name, value in sorted(initial_state.items())
        }
        if not self.global_state:
            raise DiLoCoError("initial_state cannot be empty")
        self.members = {
            worker_id: WorkerMembership(worker_id=worker_id, state=MembershipState.ACTIVE)
            for worker_id in sorted(worker_ids)
        }
        self.compressor = get_compressor(config.distributed.compression)
        self.compressor_states = {worker_id: CompressorState() for worker_id in sorted(worker_ids)}
        self.outer_optimizer = OuterOptimizer(self.job.outer_optimizer)
        self.current_round = 0
        self.active_round: _Round | None = None
        self.latest_checkpoint: Phase18CheckpointMetadata | None = None
        self.placement = dict(placement or {})
        self.metrics: list[OuterRoundMetric] = []
        self.events: list[dict[str, Any]] = []
        self.room_mac_key: str | None = None
        replay_path = Path(self.config.output_dir) / "replay-guard.json"
        self.replay_guard: ReplayGuard = FileReplayGuard(replay_path)

    @property
    def active_worker_ids(self) -> list[str]:
        return sorted(
            worker_id
            for worker_id, member in self.members.items()
            if member.state == MembershipState.ACTIVE
        )

    def should_synchronize(self, completed_local_steps: int) -> bool:
        if completed_local_steps <= 0:
            return False
        return completed_local_steps % self.job.diloco_h == 0

    def start_round(self, *, now: datetime | None = None) -> int:
        if self.active_round is not None and self.active_round.state != RoundState.FINALIZED:
            raise DiLoCoError("an outer round is already active")
        if len(self.active_worker_ids) < self.job.min_k:
            raise DiLoCoError(
                f"cannot start round below min_k: {len(self.active_worker_ids)} < {self.job.min_k}"
            )
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        number = self.current_round + 1
        self.active_round = _Round(
            number=number,
            deadline_at=current + timedelta(seconds=self.job.sync_deadline_seconds),
            opened_monotonic=time.perf_counter(),
            expected_worker_ids=self.active_worker_ids,
        )
        self.events.append({"kind": "outer_round_started", "round": number})
        return number

    def encode_update(
        self,
        *,
        worker_id: str,
        round_number: int,
        delta: dict[str, Any],
        completed_local_steps: int,
    ) -> bytes:
        if not self.should_synchronize(completed_local_steps):
            raise DiLoCoError(
                f"worker has not completed the configured H={self.job.diloco_h} local steps"
            )
        member = self.members.get(worker_id)
        if member is None or member.state != MembershipState.ACTIVE:
            raise DiLoCoError("inactive worker cannot encode an outer update")
        if member.bootstrapped_round < round_number - 1:
            raise DiLoCoError("worker must bootstrap the latest checkpoint before this round")
        return _encode_outer_update(
            room_id=self.room_id,
            run_id=self.run_id,
            worker_id=worker_id,
            round_number=round_number,
            delta=delta,
            global_state=self.global_state,
            compressor=self.compressor,
            compressor_state=self.compressor_states[worker_id],
            room_mac_key=self.room_mac_key,
        )

    def submit_encoded(self, encoded: bytes) -> UpdateReceipt:  # noqa: C901
        envelope = BinaryEnvelope.decode(
            encoded,
            expected_room_id=self.room_id,
            expected_run_id=self.run_id,
        )
        worker_id = envelope.worker_id
        round_number = envelope.round
        active = self.active_round
        if active is None or round_number < self.current_round + 1:
            return self._reject(UpdateDisposition.LATE, worker_id, round_number, "round finalized")
        if round_number != active.number:
            return self._reject(
                UpdateDisposition.STALE,
                worker_id,
                round_number,
                "update is not for the active round",
            )
        if active.state == RoundState.FINALIZED:
            return self._reject(UpdateDisposition.LATE, worker_id, round_number, "round finalized")
        if active.state == RoundState.PAUSED:
            return self._reject(UpdateDisposition.LATE, worker_id, round_number, "round is paused")
        member = self.members.get(worker_id)
        if member is None or member.state != MembershipState.ACTIVE:
            return self._reject(
                UpdateDisposition.INACTIVE, worker_id, round_number, "worker inactive"
            )
        if member.bootstrapped_round < round_number - 1:
            return self._reject(
                UpdateDisposition.STALE,
                worker_id,
                round_number,
                "worker has not bootstrapped the latest checkpoint",
            )
        if worker_id in active.updates or envelope.transfer_id in active.transfer_ids:
            return self._reject(
                UpdateDisposition.DUPLICATE,
                worker_id,
                round_number,
                "duplicate worker update",
            )
        if envelope.payload_type != "diloco_outer_delta":
            raise DiLoCoError("unexpected binary payload type")
        if self.room_mac_key and b"|mac=" in (envelope.extensions or b""):
            from deepiri_zepgpu.training.integrity import (
                UpdateIntegrityError,
                accept_live_outer_envelope,
            )

            try:
                accept_live_outer_envelope(
                    envelope,
                    room_id=self.room_id,
                    run_id=self.run_id,
                    room_mac_key=self.room_mac_key,
                    replay_guard=self.replay_guard,
                )
            except UpdateIntegrityError as exc:
                return self._reject(
                    UpdateDisposition.STALE, worker_id, round_number, f"integrity: {exc}"
                )
        if envelope.compression != self.config.codec_id():
            raise DiLoCoError("outer update compressor does not match run config")
        compressed = CompressedUpdate(
            codec=envelope.compression,
            payload=envelope.payload,
            shapes=(),
            dtypes=(),
            names=(),
            uncompressed_bytes=0,
            compressed_bytes=len(envelope.payload),
        )
        decoded = {
            name: np.asarray(value, dtype=np.float32)
            for name, value in self.compressor.decompress(compressed).items()
        }
        validate_matching_shapes(self.global_state, decoded)
        active.updates[worker_id] = decoded
        active.transfer_ids.add(envelope.transfer_id)
        try:
            ext = envelope.extensions.decode("ascii").split("|", 1)[0]
            uncompressed_bytes = int(ext)
        except (UnicodeDecodeError, ValueError):
            uncompressed_bytes = sum(item.nbytes for item in decoded.values())
        active.uncompressed_bytes += uncompressed_bytes
        active.compressed_bytes += len(envelope.payload)
        self.events.append(
            {"kind": "outer_update_accepted", "round": round_number, "worker_id": worker_id}
        )
        return UpdateReceipt(
            UpdateDisposition.ACCEPTED, worker_id, round_number, "outer update accepted"
        )

    def _reject(
        self,
        disposition: UpdateDisposition,
        worker_id: str,
        round_number: int,
        reason: str,
    ) -> UpdateReceipt:
        payload = {
            "kind": "outer_update_rejected",
            "disposition": disposition.value,
            "round": round_number,
            "worker_id": worker_id,
            "reason": reason,
        }
        self.events.append(payload)
        if self.active_round is not None:
            self.active_round.rejected.append(payload)
        return UpdateReceipt(disposition, worker_id, round_number, reason)

    def finalize_round(
        self,
        *,
        now: datetime | None = None,
        allow_min_k_before_deadline: bool = False,
    ) -> OuterRoundMetric | None:
        active = self.active_round
        if active is None:
            raise DiLoCoError("no active outer round")
        if active.state == RoundState.FINALIZED:
            return self.metrics[-1]
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        accepted = len(active.updates)
        expected_active = self.active_worker_ids
        all_available = accepted >= len(expected_active)
        deadline_reached = current >= active.deadline_at
        if not all_available and not deadline_reached and not allow_min_k_before_deadline:
            return None
        if accepted < self.job.min_k:
            if not deadline_reached:
                return None
            active.state = RoundState.PAUSED
            metric = self._round_metric(active)
            self.events.append(
                {
                    "kind": "outer_round_paused",
                    "round": active.number,
                    "accepted": accepted,
                    "min_k": self.job.min_k,
                }
            )
            return metric
        ordered_updates = [active.updates[worker] for worker in sorted(active.updates)]
        averaged = {
            name: np.mean(
                np.stack([update[name] for update in ordered_updates], axis=0), axis=0
            ).astype(np.float32)
            for name in sorted(self.global_state)
        }
        self.global_state = self.outer_optimizer.apply(self.global_state, averaged)
        active.state = RoundState.FINALIZED
        self.current_round = active.number
        for worker_id in active.updates:
            self.members[worker_id].bootstrapped_round = self.current_round
        metric = self._round_metric(active)
        self.metrics.append(metric)
        self.events.append(
            {
                "kind": "outer_round_finalized",
                "round": self.current_round,
                "accepted_worker_ids": sorted(active.updates),
                "straggler_worker_ids": metric.straggler_worker_ids,
            }
        )
        self.latest_checkpoint = self.create_checkpoint()
        return metric

    def _round_metric(self, active: _Round) -> OuterRoundMetric:
        ratio = (
            active.compressed_bytes / active.uncompressed_bytes
            if active.uncompressed_bytes
            else 0.0
        )
        return OuterRoundMetric(
            round_number=active.number,
            state=active.state,
            expected_workers=len(active.expected_worker_ids),
            accepted_workers=len(active.updates),
            min_k=self.job.min_k,
            straggler_worker_ids=sorted(set(active.expected_worker_ids) - set(active.updates)),
            blocked_sync_seconds=max(0.0, time.perf_counter() - active.opened_monotonic),
            uncompressed_bytes=active.uncompressed_bytes,
            compressed_bytes=active.compressed_bytes,
            compression_ratio=ratio,
        )

    def mark_failed(self, worker_id: str, *, reason: str) -> None:
        member = self._member(worker_id)
        member.state = MembershipState.FAILED
        member.reason = reason
        self.events.append({"kind": "worker_failed", "worker_id": worker_id, "reason": reason})

    def graceful_leave(self, worker_id: str, *, reason: str = "graceful leave") -> None:
        member = self._member(worker_id)
        member.state = MembershipState.LEFT
        member.reason = reason
        self.events.append({"kind": "worker_left", "worker_id": worker_id, "reason": reason})

    def request_join(self, worker_id: str) -> Phase18CheckpointMetadata | None:
        member = self.members.get(worker_id)
        if member is None:
            member = WorkerMembership(worker_id=worker_id, state=MembershipState.BOOTSTRAPPING)
            self.members[worker_id] = member
            self.compressor_states[worker_id] = CompressorState()
        elif self.current_round == 0:
            member.state = MembershipState.ACTIVE
            member.bootstrapped_round = 0
        else:
            member.state = MembershipState.BOOTSTRAPPING
        # Error-feedback residuals are local to the state that produced them. A
        # checkpoint bootstrap starts from the current global state, so stale
        # pre-failure residuals must not leak into the rejoined worker's update.
        self.compressor_states[worker_id] = CompressorState()
        self.events.append({"kind": "worker_join_requested", "worker_id": worker_id})
        record_rejoin(room_id=self.room_id, result="ok")
        return self.latest_checkpoint

    def bootstrap_worker(
        self, worker_id: str, checkpoint: Phase18CheckpointMetadata
    ) -> dict[str, np.ndarray]:
        member = self._member(worker_id)
        if checkpoint.run_id != self.run_id:
            raise DiLoCoError("checkpoint belongs to a different run")
        if checkpoint.outer_round != self.current_round:
            raise DiLoCoError("worker must bootstrap the latest finalized outer round")
        restored = _arrays_from_json(checkpoint.model_state)
        validate_matching_shapes(self.global_state, restored)
        for name in self.global_state:
            if not np.array_equal(self.global_state[name], restored[name]):
                raise DiLoCoError("checkpoint model state is not the current global state")
        member.state = MembershipState.ACTIVE
        member.bootstrapped_round = checkpoint.outer_round
        member.rejoin_count += 1
        member.reason = None
        self.events.append(
            {
                "kind": "checkpoint_bootstrap",
                "worker_id": worker_id,
                "round": checkpoint.outer_round,
            }
        )
        return {name: value.copy() for name, value in restored.items()}

    def create_checkpoint(self, *, save: bool = False) -> Phase18CheckpointMetadata:
        directory = Path(self.config.output_dir) / f"checkpoint-outer-{self.current_round}"
        checkpoint = make_phase18_checkpoint_metadata(
            run_id=self.run_id,
            step=self.current_round * self.job.diloco_h,
            outer_round=self.current_round,
            directory=directory,
            config=self.config.to_public_dict(),
            model_state=_arrays_to_json(self.global_state),
            outer_optimizer_state=self.outer_optimizer.state_dict(),
            active_membership=self.active_worker_ids,
            compression_config=self.config.distributed.compression.model_dump(mode="json"),
            placement=self.placement,
            island_ids=list(self.placement.get("selected_island_ids", [])),
        )
        if save:
            from deepiri_zepgpu.training.recovery import write_checkpoint_integrity

            write_checkpoint_integrity(directory, checkpoint)
            record_checkpoint(room_id=self.room_id, operation="save", result="ok")
        return checkpoint

    def restore_verified_checkpoint(self, directory: Path) -> Phase18CheckpointMetadata:
        from deepiri_zepgpu.training.recovery import load_verified_checkpoint

        checkpoint = load_verified_checkpoint(directory)
        self.restore_checkpoint(checkpoint)
        return checkpoint

    def restore_checkpoint(self, checkpoint: Phase18CheckpointMetadata) -> None:
        if checkpoint.run_id != self.run_id:
            raise DiLoCoError("checkpoint belongs to a different run")
        self.global_state = _arrays_from_json(checkpoint.model_state)
        self.outer_optimizer.load_state_dict(checkpoint.outer_optimizer_state)
        self.current_round = checkpoint.outer_round
        self.latest_checkpoint = checkpoint
        self.active_round = None
        for worker_id, member in self.members.items():
            member.bootstrapped_round = checkpoint.outer_round
            member.state = (
                MembershipState.ACTIVE
                if worker_id in checkpoint.active_membership
                else MembershipState.BOOTSTRAPPING
            )

    def _member(self, worker_id: str) -> WorkerMembership:
        member = self.members.get(worker_id)
        if member is None:
            raise DiLoCoError(f"unknown worker {worker_id}")
        return member
