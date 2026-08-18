import asyncio
import uuid

import pytest

from deepiri_zepgpu.training.binary import BinaryEnvelope, BinaryInbox
from deepiri_zepgpu.training.relay import BinaryRelayStore
from deepiri_zepgpu.training.transport import (
    InMemoryDirectChannel,
    PcclDirectChannel,
    TransferManager,
)
from deepiri_zepgpu.training.worker import PersistentTrainingWorker, WorkerEvent, WorkerState


def envelope() -> BinaryEnvelope:
    return BinaryEnvelope(
        room_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        worker_id=str(uuid.uuid4()),
        transfer_id=str(uuid.uuid4()),
        round=1,
        payload_type="gradient",
        shape=(4,),
        dtype="float32",
        compression="zstd",
        payload=b"binary-gradient",
    )


@pytest.mark.asyncio
async def test_direct_exchange_and_relay_fallback_metrics() -> None:
    direct = InMemoryDirectChannel()
    received: list[bytes] = []

    async def receive(data: bytes) -> None:
        received.append(data)

    target = str(uuid.uuid4())
    direct.register(target, receive)
    manager = TransferManager(direct=direct, relay=BinaryRelayStore(), max_retries=1)
    item = envelope()
    relayed, metric = await manager.send(item, target)
    assert relayed is None
    assert BinaryEnvelope.decode(received[0]) == item
    assert metric.path == "direct"
    assert metric.bytes > len(item.payload)

    store = BinaryRelayStore()
    fallback = TransferManager(direct=PcclDirectChannel(), relay=store, chunk_size=7, max_retries=1)
    target_worker = str(uuid.uuid4())
    relayed, metric = await fallback.send(item, target_worker)
    assert relayed is None
    downloaded = await fallback.relay.download(  # type: ignore[attr-defined]
        item.transfer_id,
        room_id=item.room_id,
        run_id=item.run_id,
        source_worker_id=item.worker_id,
        round_number=item.round,
        target_worker_id=target_worker,
    )
    target_inbox = BinaryInbox(room_id=item.room_id, run_id=item.run_id)
    assert target_inbox.receive(downloaded.encode()) == item
    assert metric.path == "relay"
    assert metric.retries == 1
    assert metric.duration_seconds >= 0


class Coordinator:
    def __init__(self) -> None:
        self.online = True
        self.authenticated: list[str] = []
        self.events: list[tuple[str, WorkerEvent]] = []

    async def authenticate(
        self, worker_id: str, provider_token: str, run_credential: str | None
    ) -> None:
        if not self.online:
            raise ConnectionError
        assert provider_token
        self.authenticated.append(worker_id)

    async def event(self, worker_id: str, event: WorkerEvent) -> None:
        if not self.online:
            raise ConnectionError
        self.events.append((worker_id, event))


@pytest.mark.asyncio
async def test_two_workers_persist_across_rounds_reconnect_and_restart() -> None:
    coordinator = Coordinator()
    workers = [
        PersistentTrainingWorker(
            worker_id=str(uuid.uuid4()), provider_token="provider", coordinator=coordinator
        )
        for _ in range(2)
    ]
    for worker in workers:
        await worker.start()
        for round_number in range(1, 4):
            result = await worker.run_round(
                round_number, lambda round_number=round_number: _result(round_number)
            )
            assert result == {"round": round_number}
        assert worker.state == WorkerState.READY
        assert worker.round == 3

    coordinator.online = False
    await workers[0].heartbeat({"loss": 1.0})
    assert workers[0].state == WorkerState.RECONNECTING
    assert workers[0].buffered_event_count == 1
    coordinator.online = True
    await workers[0].reconnect()
    assert workers[0].state == WorkerState.READY
    assert workers[0].buffered_event_count == 0

    await workers[1].shutdown()
    assert workers[1].state == WorkerState.STOPPED
    await workers[1].restart()
    assert workers[1].state == WorkerState.READY
    assert workers[1].restart_count == 1
    await workers[1].shutdown(force=True)
    assert workers[1].state == WorkerState.ABORTED


@pytest.mark.asyncio
async def test_worker_failure_recovers_and_emits_failure() -> None:
    coordinator = Coordinator()
    worker = PersistentTrainingWorker(
        worker_id=str(uuid.uuid4()), provider_token="provider", coordinator=coordinator
    )
    await worker.start()

    async def fail() -> None:
        raise RuntimeError("sensitive details are not emitted")

    with pytest.raises(RuntimeError):
        await worker.run_round(1, fail)
    assert worker.state == WorkerState.READY
    failure = coordinator.events[-1][1]
    assert failure.kind == "round_failed"
    assert failure.payload == {"round": 1, "error_type": "RuntimeError"}


@pytest.mark.asyncio
async def test_worker_force_abort_cancels_active_round() -> None:
    coordinator = Coordinator()
    worker = PersistentTrainingWorker(
        worker_id=str(uuid.uuid4()), provider_token="provider", coordinator=coordinator
    )
    await worker.start()
    started = asyncio.Event()

    async def block() -> None:
        started.set()
        await asyncio.Event().wait()

    round_task = asyncio.create_task(worker.run_round(1, block))
    await started.wait()
    await worker.shutdown(force=True)
    with pytest.raises(asyncio.CancelledError):
        await round_task
    assert worker.state == WorkerState.ABORTED


@pytest.mark.asyncio
async def test_worker_buffers_events_in_order_and_tracks_overflow() -> None:
    coordinator = Coordinator()
    worker = PersistentTrainingWorker(
        worker_id=str(uuid.uuid4()),
        provider_token="provider",
        coordinator=coordinator,
        buffer_limit=2,
    )
    await worker.start()
    coordinator.online = False
    await worker.heartbeat({"sequence": 1})
    await worker.log("buffered", {"sequence": 2})
    await worker.heartbeat({"sequence": 3})
    assert worker.buffered_event_count == 2
    assert worker.dropped_event_count == 1
    coordinator.online = True
    await worker.reconnect()
    buffered = [event for _, event in coordinator.events[-3:-1]]
    assert [event.kind for event in buffered] == ["log", "heartbeat"]
    assert buffered[0].payload["payload"]["sequence"] == 2
    assert buffered[1].payload["progress"]["sequence"] == 3


def test_transport_limits_are_validated() -> None:
    direct = PcclDirectChannel()
    relay = BinaryRelayStore()
    with pytest.raises(ValueError):
        TransferManager(direct=direct, relay=relay, chunk_size=0)
    with pytest.raises(ValueError):
        TransferManager(direct=direct, relay=relay, max_retries=-1)


@pytest.mark.asyncio
async def test_direct_authorization_failure_does_not_fall_back() -> None:
    class UnauthorizedDirect:
        async def send(self, target_worker_id: str, encoded: bytes) -> None:
            raise PermissionError("target authorization failed")

    class UnexpectedRelay:
        called = False

        async def transfer(self, item: BinaryEnvelope, target_worker_id: str) -> BinaryEnvelope:
            self.called = True
            return item

    relay = UnexpectedRelay()
    manager = TransferManager(direct=UnauthorizedDirect(), relay=relay)
    with pytest.raises(PermissionError, match="authorization"):
        await manager.send(envelope(), str(uuid.uuid4()))
    assert not relay.called


async def _result(round_number: int) -> dict[str, int]:
    return {"round": round_number}
