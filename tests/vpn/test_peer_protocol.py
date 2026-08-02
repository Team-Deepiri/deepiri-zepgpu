"""Security regression tests for the strict WireGuard peer protocol."""

from __future__ import annotations

import base64
import importlib
import json
import pickle
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from deepiri_zepgpu.vpn.peer_node import app, configure_peer_protocol
from deepiri_zepgpu.vpn.peer_protocol import (
    MAX_ENCODED_MESSAGE_SIZE,
    MAX_GPU_MEMORY_MB,
    ExecuteTaskMessage,
    NoopResult,
    ProtocolError,
    TaskResultMessage,
    calculate_integrity,
    canonical_json,
    create_execute_message,
    create_result_message,
    decode_message,
    encode_message,
)

ROOM_ID = "11111111-1111-4111-8111-111111111111"
SENDER_ID = "22222222-2222-4222-8222-222222222222"
OTHER_SENDER_ID = "33333333-3333-4333-8333-333333333333"
RECIPIENT_ID = "44444444-4444-4444-8444-444444444444"
OTHER_ROOM_ID = "55555555-5555-4555-8555-555555555555"
TOKEN = "sender-token-that-is-at-least-thirty-two-bytes"
OTHER_TOKEN = "other-sender-token-that-is-at-least-thirty-two-bytes"

JSON_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


@pytest.fixture(autouse=True)
def configured_protocol() -> None:
    configure_peer_protocol(
        room_id=ROOM_ID,
        peer_id=RECIPIENT_ID,
        authorized_peer_tokens={SENDER_ID: TOKEN, OTHER_SENDER_ID: OTHER_TOKEN},
    )


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _request_message(**overrides: object) -> ExecuteTaskMessage:
    values: dict[str, object] = {
        "secret": TOKEN,
        "message_id": str(uuid4()),
        "room_id": ROOM_ID,
        "sender_peer_id": SENDER_ID,
        "recipient_peer_id": RECIPIENT_ID,
        "task_id": str(uuid4()),
        "issued_at": int(time.time()),
        "gpu_device_id": 0,
        "gpu_memory_mb": 1024,
        "timeout_seconds": 60,
        "message": "safe noop",
    }
    values.update(overrides)
    return create_execute_message(**values)  # type: ignore[arg-type]


def _mutated_bytes(
    message: ExecuteTaskMessage,
    *,
    resign: bool = False,
    secret: str = TOKEN,
    **updates: object,
) -> bytes:
    payload = message.model_dump(mode="json")
    payload.update(updates)
    if resign:
        payload["integrity"] = calculate_integrity(payload, secret)
    return canonical_json(payload)


def _post(client: TestClient, raw: bytes, headers: dict[str, str] | None = None):
    return client.post("/execute", content=raw, headers=headers or JSON_HEADERS)


def _write_marker(path: str) -> None:
    Path(path).write_text("unsafe deserializer executed", encoding="utf-8")


class _MaliciousReduce:
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self):
        return _write_marker, (str(self.marker),)


def test_valid_request_and_result_round_trip() -> None:
    request = _request_message()
    decoded_request = decode_message(
        encode_message(request),
        secret=TOKEN,
        expected_kind="task.execute",
    )
    assert decoded_request == request

    result = create_result_message(
        secret=TOKEN,
        message_id=str(uuid4()),
        request_message_id=request.message_id,
        room_id=ROOM_ID,
        sender_peer_id=RECIPIENT_ID,
        recipient_peer_id=SENDER_ID,
        task_id=request.task_id,
        success=True,
        result=NoopResult(message="safe noop"),
        error=None,
        execution_time=0.01,
    )
    decoded_result = decode_message(
        encode_message(result),
        secret=TOKEN,
        expected_kind="task.result",
    )
    assert decoded_result == result


def test_valid_noop_endpoint_round_trip(client: TestClient) -> None:
    request = _request_message()
    response = _post(client, encode_message(request))
    assert response.status_code == 200, response.text

    result = decode_message(
        response.content,
        secret=TOKEN,
        expected_kind="task.result",
    )
    assert isinstance(result, TaskResultMessage)
    assert result.request_message_id == request.message_id
    assert result.task_id == request.task_id
    assert result.room_id == ROOM_ID
    assert result.sender_peer_id == RECIPIENT_ID
    assert result.recipient_peer_id == SENDER_ID
    assert result.success is True
    assert result.result == NoopResult(message="safe noop")


@pytest.mark.parametrize(
    ("updates", "expected_detail"),
    [
        ({"version": 2}, "Unsupported peer protocol version"),
        ({"kind": "task.unknown"}, "Unknown peer message kind"),
    ],
)
def test_rejects_unsupported_version_and_unknown_kind(
    client: TestClient,
    updates: dict[str, object],
    expected_detail: str,
) -> None:
    response = _post(client, _mutated_bytes(_request_message(), **updates))
    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail


def test_rejects_missing_required_field(client: TestClient) -> None:
    payload = _request_message().model_dump(mode="json")
    payload.pop("task_id")
    response = _post(client, canonical_json(payload))
    assert response.status_code == 400
    assert response.json()["detail"] == "Peer message schema validation failed"


def test_rejects_unexpected_field(client: TestClient) -> None:
    response = _post(client, _mutated_bytes(_request_message(), unexpected="value"))
    assert response.status_code == 400
    assert response.json()["detail"] == "Peer message schema validation failed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gpu_device_id", "0"),
        ("gpu_memory_mb", True),
        ("timeout_seconds", 1.5),
        ("payload", []),
    ],
)
def test_rejects_wrong_field_types(
    client: TestClient,
    field: str,
    value: object,
) -> None:
    response = _post(client, _mutated_bytes(_request_message(), **{field: value}))
    assert response.status_code == 400
    assert response.json()["detail"] == "Peer message schema validation failed"


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b'{"version":1',
        b'{"version":1}trailing',
        b"\xff\xfe\xfd",
        b'{"version":1,"version":1}',
    ],
)
def test_rejects_malformed_truncated_trailing_invalid_utf8_and_duplicate_fields(
    client: TestClient,
    raw: bytes,
) -> None:
    response = _post(client, raw)
    assert response.status_code == 400


def test_rejects_oversized_encoded_message(client: TestClient) -> None:
    raw = b"{" + (b"x" * MAX_ENCODED_MESSAGE_SIZE) + b"}"
    response = _post(client, raw)
    assert response.status_code == 413


def test_rejects_oversized_claim_before_reading_body(client: TestClient) -> None:
    headers = dict(JSON_HEADERS)
    headers["Content-Length"] = str(MAX_ENCODED_MESSAGE_SIZE + 1)
    response = _post(client, b"{}", headers)
    assert response.status_code == 413


@pytest.mark.parametrize(
    "updates",
    [
        {"gpu_memory_mb": MAX_GPU_MEMORY_MB + 1},
        {"payload": {"message": "x" * 257}},
    ],
)
def test_rejects_oversized_claimed_fields(
    client: TestClient,
    updates: dict[str, object],
) -> None:
    response = _post(client, _mutated_bytes(_request_message(), **updates))
    assert response.status_code == 400
    assert response.json()["detail"] == "Peer message schema validation failed"


def test_rejects_wrong_room(client: TestClient) -> None:
    raw = _mutated_bytes(_request_message(), room_id=OTHER_ROOM_ID, resign=True)
    response = _post(client, raw)
    assert response.status_code == 403
    assert response.json()["detail"] == "Message is outside this room"


def test_rejects_wrong_recipient(client: TestClient) -> None:
    raw = _mutated_bytes(_request_message(), recipient_peer_id=OTHER_SENDER_ID, resign=True)
    response = _post(client, raw)
    assert response.status_code == 403
    assert response.json()["detail"] == "Message targets a different peer"


def test_rejects_sender_identity_mismatch(client: TestClient) -> None:
    raw = _mutated_bytes(_request_message(), sender_peer_id=OTHER_SENDER_ID, resign=True)
    response = _post(client, raw)
    assert response.status_code == 403
    assert response.json()["detail"] == "Sender identity does not match credentials"


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer wrong-token-that-is-at-least-thirty-two-bytes"],
)
def test_rejects_unauthorized_peer(
    client: TestClient,
    authorization: str | None,
) -> None:
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    response = _post(client, encode_message(_request_message()), headers)
    assert response.status_code == 401


def test_rejects_invalid_integrity(client: TestClient) -> None:
    response = _post(client, _mutated_bytes(_request_message(), integrity="0" * 64))
    assert response.status_code == 401
    assert response.json()["detail"] == "Peer message integrity check failed"


@pytest.mark.parametrize(
    ("issued_at_offset", "expected_detail"),
    [
        (-360, "Peer message has expired"),
        (60, "Peer message timestamp is in the future"),
    ],
)
def test_rejects_messages_outside_timestamp_window(
    client: TestClient,
    issued_at_offset: int,
    expected_detail: str,
) -> None:
    issued_at = int(time.time()) + issued_at_offset
    response = _post(client, encode_message(_request_message(issued_at=issued_at)))
    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail


def test_rejects_non_json_content_type(client: TestClient) -> None:
    response = _post(
        client,
        encode_message(_request_message()),
        {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 415


def test_rejects_tampered_result_integrity() -> None:
    request = _request_message()
    result = create_result_message(
        secret=TOKEN,
        message_id=str(uuid4()),
        request_message_id=request.message_id,
        room_id=ROOM_ID,
        sender_peer_id=RECIPIENT_ID,
        recipient_peer_id=SENDER_ID,
        task_id=request.task_id,
        success=True,
        result=NoopResult(message="safe noop"),
        error=None,
        execution_time=0.01,
    )
    payload = result.model_dump(mode="json")
    payload["result"] = {"status": "ok", "message": "tampered"}
    with pytest.raises(ProtocolError, match="integrity check failed"):
        decode_message(canonical_json(payload), secret=TOKEN, expected_kind="task.result")


def test_rejects_replay_and_duplicate_task(client: TestClient) -> None:
    request = _request_message()
    raw = encode_message(request)
    assert _post(client, raw).status_code == 200

    replay = _post(client, raw)
    assert replay.status_code == 409
    assert replay.json()["detail"] == "Duplicate peer message"

    duplicate_task = _request_message(task_id=request.task_id)
    duplicate = _post(client, encode_message(duplicate_task))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Duplicate peer task"


def test_cached_result_is_limited_to_original_sender(client: TestClient) -> None:
    request = _request_message()
    assert _post(client, encode_message(request)).status_code == 200

    own_result = client.get(
        f"/result/{request.task_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert own_result.status_code == 200

    other_result = client.get(
        f"/result/{request.task_id}",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert other_result.status_code == 403


def test_raw_and_legacy_base64_pickle_payloads_cannot_execute_reduce(
    client: TestClient,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "pickle-executed.txt"
    malicious_pickle = pickle.dumps(_MaliciousReduce(marker))

    raw_response = _post(client, malicious_pickle)
    assert raw_response.status_code == 400
    assert not marker.exists()

    legacy_payload = {
        "task_id": str(uuid4()),
        "func_encoded": base64.b64encode(malicious_pickle).decode("ascii"),
        "args_encoded": base64.b64encode(pickle.dumps(())).decode("ascii"),
        "kwargs_encoded": base64.b64encode(pickle.dumps({})).decode("ascii"),
        "gpu_device_id": 0,
        "gpu_memory_mb": 1,
        "timeout_seconds": 1,
    }
    legacy_response = _post(
        client,
        json.dumps(legacy_payload, separators=(",", ":")).encode("utf-8"),
    )
    assert legacy_response.status_code == 400
    assert not marker.exists()


def test_payload_cannot_trigger_dynamic_module_or_class_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[tuple[object, ...]] = []

    def reject_import(*args: object, **_kwargs: object) -> None:
        imports.append(args)
        raise AssertionError("payload-triggered import attempted")

    monkeypatch.setattr(importlib, "import_module", reject_import)
    raw = _mutated_bytes(_request_message(), operation="os.system")
    with pytest.raises(ProtocolError, match="schema validation"):
        decode_message(raw, secret=TOKEN, expected_kind="task.execute")
    assert imports == []
