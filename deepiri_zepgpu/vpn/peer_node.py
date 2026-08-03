"""Peer node: GPU exposer and task receiver for remote GPU sharing."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from deepiri_zepgpu.vpn.config import vpn_settings
from deepiri_zepgpu.vpn.peer_protocol import (
    MAX_AUTH_TOKEN_LENGTH,
    MAX_ENCODED_MESSAGE_SIZE,
    MESSAGE_FUTURE_SKEW_SECONDS,
    MESSAGE_MAX_AGE_SECONDS,
    ExecuteTaskMessage,
    NoopResult,
    ProtocolError,
    TaskResultMessage,
    canonical_json,
    create_result_message,
    decode_message,
    normalize_uuid,
    validate_protocol_secret,
)

app = FastAPI(title="ZepGPU Peer Node")


class GpuInfo(BaseModel):
    device_index: int
    name: str | None = None
    total_memory_mb: int
    available_memory_mb: int
    compute_capability: str | None = None
    gpu_type: str = "nvidia"
    state: str = "idle"
    utilization_percent: float | None = None


_MAX_AUTHORIZED_PEERS = 1024
_MAX_CACHED_RESULTS = 1024
_MAX_SEEN_MESSAGES = 4096

_task_results: OrderedDict[str, TaskResultMessage] = OrderedDict()
_task_result_owners: dict[str, str] = {}
_seen_message_ids: OrderedDict[str, float] = OrderedDict()
_protocol_lock = threading.Lock()
_local_gpus: list[GpuInfo] = []
_relay_url: str = ""
_peer_id: str = ""
_room_id: str = ""
_vpn_ip: str = ""
_authorized_peer_tokens: dict[str, str] = {}
_ledger_private_key: str = ""
_ledger_public_key: str = ""


try:
    import pynvml

    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False


def discover_local_gpus() -> list[GpuInfo]:
    """Discover local GPUs using NVML."""
    gpus: list[GpuInfo] = []
    if not PYNVML_AVAILABLE:
        return gpus

    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle) or f"GPU-{i}"
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_mb = mem_info.total // (1024 * 1024)
            free_mb = mem_info.free // (1024 * 1024)

            try:
                cc = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                cc_str = f"{cc.major}.{cc.minor}"
            except Exception:
                cc_str = "0.0"

            gpus.append(
                GpuInfo(
                    device_index=i,
                    name=name,
                    total_memory_mb=total_mb,
                    available_memory_mb=free_mb,
                    compute_capability=cc_str,
                )
            )
        pynvml.nvmlShutdown()
    except Exception:
        pass

    return gpus


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "vpn_ip": _vpn_ip, "peer_id": _peer_id}


@app.get("/gpu/status")
async def gpu_status() -> dict:
    return {"gpus": _local_gpus, "timestamp": datetime.now(UTC).isoformat()}


def configure_peer_protocol(
    *,
    room_id: str,
    peer_id: str,
    authorized_peer_tokens: Mapping[str, str],
) -> None:
    """Configure an explicit room scope and sender-specific peer credentials."""
    if not authorized_peer_tokens:
        raise ValueError("At least one authorized sender is required")
    if len(authorized_peer_tokens) > _MAX_AUTHORIZED_PEERS:
        raise ValueError("Too many authorized peer identities")

    normalized_room_id = normalize_uuid(room_id, "room_id")
    normalized_peer_id = normalize_uuid(peer_id, "peer_id")
    normalized_tokens: dict[str, str] = {}
    for sender_peer_id, token in authorized_peer_tokens.items():
        normalized_sender = normalize_uuid(sender_peer_id, "authorized sender peer_id")
        validate_protocol_secret(token)
        normalized_tokens[normalized_sender] = token

    global _room_id, _peer_id, _authorized_peer_tokens
    with _protocol_lock:
        _room_id = normalized_room_id
        _peer_id = normalized_peer_id
        _authorized_peer_tokens = normalized_tokens
        _task_results.clear()
        _task_result_owners.clear()
        _seen_message_ids.clear()


def _authenticate_sender(authorization: str | None) -> tuple[str, str]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token:
        raise HTTPException(status_code=401, detail="Invalid bearer credentials")
    if len(token.encode("utf-8")) > MAX_AUTH_TOKEN_LENGTH:
        raise HTTPException(status_code=401, detail="Invalid bearer credentials")

    authenticated_peer_id: str | None = None
    authenticated_token: str | None = None
    for candidate_peer_id, candidate_token in _authorized_peer_tokens.items():
        if hmac.compare_digest(candidate_token, token):
            authenticated_peer_id = candidate_peer_id
            authenticated_token = candidate_token
    if authenticated_peer_id is None or authenticated_token is None:
        raise HTTPException(status_code=401, detail="Invalid bearer credentials")
    return authenticated_peer_id, authenticated_token


async def _read_bounded_json(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            claimed_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if claimed_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if claimed_length > MAX_ENCODED_MESSAGE_SIZE:
            raise HTTPException(status_code=413, detail="Peer message is too large")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_ENCODED_MESSAGE_SIZE:
            raise HTTPException(status_code=413, detail="Peer message is too large")
        body.extend(chunk)
    return bytes(body)


def _authorize_message(message: ExecuteTaskMessage, authenticated_peer_id: str) -> None:
    if message.sender_peer_id != authenticated_peer_id:
        raise HTTPException(status_code=403, detail="Sender identity does not match credentials")
    if message.room_id != _room_id:
        raise HTTPException(status_code=403, detail="Message is outside this room")
    if message.recipient_peer_id != _peer_id:
        raise HTTPException(status_code=403, detail="Message targets a different peer")

    now = int(time.time())
    if message.issued_at < now - MESSAGE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=409, detail="Peer message has expired")
    if message.issued_at > now + MESSAGE_FUTURE_SKEW_SECONDS:
        raise HTTPException(status_code=409, detail="Peer message timestamp is in the future")


def _claim_message(message: ExecuteTaskMessage) -> None:
    now = time.monotonic()
    with _protocol_lock:
        while _seen_message_ids:
            _, oldest_seen = next(iter(_seen_message_ids.items()))
            if now - oldest_seen <= MESSAGE_MAX_AGE_SECONDS:
                break
            _seen_message_ids.popitem(last=False)
        if message.message_id in _seen_message_ids:
            raise HTTPException(status_code=409, detail="Duplicate peer message")
        if message.task_id in _task_results:
            raise HTTPException(status_code=409, detail="Duplicate peer task")
        _seen_message_ids[message.message_id] = now
        while len(_seen_message_ids) > _MAX_SEEN_MESSAGES:
            _seen_message_ids.popitem(last=False)


def _store_result(result: TaskResultMessage, owner_peer_id: str) -> None:
    with _protocol_lock:
        _task_results[result.task_id] = result
        _task_result_owners[result.task_id] = owner_peer_id
        while len(_task_results) > _MAX_CACHED_RESULTS:
            evicted_task_id, _ = _task_results.popitem(last=False)
            _task_result_owners.pop(evicted_task_id, None)


def _attestation_fields(
    *,
    task_id: str,
    execution_time: float,
    result_digest: str,
) -> tuple[str | None, str | None]:
    if not _ledger_private_key or not _peer_id:
        return None, None

    from deepiri_zepgpu.compute_ledger.keys import sign_message
    from deepiri_zepgpu.compute_ledger.service import hash_result_attestation

    digest = hash_result_attestation(
        task_id=task_id,
        peer_id=_peer_id,
        success=True,
        execution_time=execution_time,
        result_digest=result_digest,
    )
    return sign_message(_ledger_private_key, digest), _ledger_public_key or None


@app.post("/execute", response_model=TaskResultMessage)
async def execute_task(
    request: Request,
    authorization: str | None = Header(default=None),
) -> TaskResultMessage:
    """Execute one authenticated fixed operation; legacy pickle payloads are rejected."""
    if not _room_id or not _peer_id or not _authorized_peer_tokens:
        raise HTTPException(status_code=503, detail="Peer protocol is not configured")

    authenticated_peer_id, token = _authenticate_sender(authorization)
    raw = await _read_bounded_json(request)
    try:
        decoded = decode_message(raw, secret=token, expected_kind="task.execute")
    except ProtocolError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not isinstance(decoded, ExecuteTaskMessage):
        raise HTTPException(status_code=400, detail="Unexpected peer message kind")

    _authorize_message(decoded, authenticated_peer_id)
    _claim_message(decoded)

    start_time = time.monotonic()
    result = NoopResult(message=decoded.payload.message)
    execution_time = time.monotonic() - start_time
    result_digest = hashlib.sha256(canonical_json(result.model_dump(mode="json"))).hexdigest()
    attestation_signature, ledger_public_key = _attestation_fields(
        task_id=decoded.task_id,
        execution_time=execution_time,
        result_digest=result_digest,
    )
    task_result = create_result_message(
        secret=token,
        message_id=str(uuid4()),
        request_message_id=decoded.message_id,
        room_id=_room_id,
        sender_peer_id=_peer_id,
        recipient_peer_id=authenticated_peer_id,
        task_id=decoded.task_id,
        success=True,
        result=result,
        error=None,
        execution_time=execution_time,
        result_digest=result_digest,
        attestation_signature=attestation_signature,
        ledger_public_key=ledger_public_key,
    )
    _store_result(task_result, authenticated_peer_id)
    return task_result


@app.get("/result/{task_id}", response_model=TaskResultMessage)
async def get_result(
    task_id: str,
    authorization: str | None = Header(default=None),
) -> TaskResultMessage:
    """Return a cached result only to the sender that created the task."""
    authenticated_peer_id, _ = _authenticate_sender(authorization)
    try:
        normalized_task_id = normalize_uuid(task_id, "task_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid task id") from exc
    with _protocol_lock:
        result = _task_results.get(normalized_task_id)
        owner_peer_id = _task_result_owners.get(normalized_task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    if owner_peer_id != authenticated_peer_id:
        raise HTTPException(status_code=403, detail="Result belongs to a different sender")
    return result


async def advertise_gpus_to_relay() -> None:
    """Periodically advertise GPU status to relay."""
    global _local_gpus
    while True:
        _local_gpus = discover_local_gpus()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{_relay_url.rstrip('/')}/api/v1/vpn/peers/heartbeat",
                    json={
                        "peer_id": _peer_id,
                        "gpu_status": [g.model_dump() for g in _local_gpus],
                        "is_online": True,
                    },
                )
        except Exception:
            pass
        await asyncio.sleep(vpn_settings.heartbeat_interval_seconds)


async def start_peer_server(
    relay_url: str,
    peer_id: str,
    vpn_ip: str,
    *,
    room_id: str,
    authorized_peer_tokens: Mapping[str, str],
    ledger_private_key: str = "",
    ledger_public_key: str = "",
) -> None:
    """Start a room-scoped peer server with explicit sender credentials."""
    global _relay_url, _vpn_ip, _ledger_private_key, _ledger_public_key
    configure_peer_protocol(
        room_id=room_id,
        peer_id=peer_id,
        authorized_peer_tokens=authorized_peer_tokens,
    )
    _relay_url = relay_url
    _vpn_ip = vpn_ip
    _ledger_private_key = ledger_private_key
    _ledger_public_key = ledger_public_key

    import uvicorn

    config = uvicorn.Config(
        app, host=vpn_ip, port=vpn_settings.peer_server_port, log_level="warning"
    )
    server = uvicorn.Server(config)
    await server.serve()
