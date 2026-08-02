"""Security tests for persisted task submissions and worker payloads."""

from __future__ import annotations

import ast
import pickle
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.task_submission_security import prepare_task_payload
from deepiri_zepgpu.queue.safe_task import (
    MAX_TASK_ARGUMENT_BYTES,
    UnsafeTaskPayloadError,
    allowed_operation_names,
    decode_task_arguments,
    decode_task_result,
    encode_task_arguments,
    encode_task_result,
    resolve_operation,
    validate_operation,
)


def _write_marker(path: str) -> None:
    Path(path).write_text("unsafe task decoder executed", encoding="utf-8")


class _MaliciousReduce:
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self):
        return _write_marker, (str(self.marker),)


def _user(role: str) -> SimpleNamespace:
    return SimpleNamespace(id="11111111-1111-4111-8111-111111111111", role=role)


def test_allowlisted_operation_and_json_arguments_round_trip() -> None:
    encoded_args, encoded_kwargs = encode_task_arguments([81], {})
    args, kwargs = decode_task_arguments(encoded_args, encoded_kwargs)
    assert validate_operation("math.sqrt") == "math.sqrt"
    assert resolve_operation("math.sqrt")(*args, **kwargs) == 9


def test_unknown_operation_fails_closed() -> None:
    with pytest.raises(UnsafeTaskPayloadError, match="Unsupported task operation"):
        resolve_operation("os.system")


def test_process_global_random_operations_are_not_exposed() -> None:
    before = random.getstate()
    assert allowed_operation_names() == ("math.sqrt",)
    with pytest.raises(UnsafeTaskPayloadError, match="Unsupported task operation"):
        resolve_operation("random.seed")
    assert random.getstate() == before


def test_legacy_callable_payload_cannot_execute_reduce(tmp_path: Path) -> None:
    marker = tmp_path / "task-pickle-executed.txt"
    malicious = pickle.dumps(_MaliciousReduce(marker)).decode("latin1")
    with pytest.raises(UnsafeTaskPayloadError, match="Serialized Python callables"):
        validate_operation(None, malicious)
    assert not marker.exists()


def test_ordinary_user_cannot_submit_worker_task() -> None:
    with pytest.raises(HTTPException) as exc:
        prepare_task_payload(
            user=_user("user"),  # type: ignore[arg-type]
            func_name="math.sqrt",
            serialized_func=None,
            args=[4],
            kwargs={},
        )
    assert exc.value.status_code == 403


def test_researcher_can_submit_only_primitive_allowlisted_task() -> None:
    user, operation, args, kwargs = prepare_task_payload(
        user=_user("researcher"),  # type: ignore[arg-type]
        func_name="math.sqrt",
        serialized_func=None,
        args=[4],
        kwargs={},
    )
    assert user.id == "11111111-1111-4111-8111-111111111111"
    assert operation == "math.sqrt"
    assert decode_task_arguments(args, kwargs) == ([4], {})


def test_api_rejects_legacy_executable_payload_with_gone() -> None:
    with pytest.raises(HTTPException) as exc:
        prepare_task_payload(
            user=_user("admin"),  # type: ignore[arg-type]
            func_name=None,
            serialized_func="legacy-pickle",
            args=[],
            kwargs={},
        )
    assert exc.value.status_code == 410


def test_task_payload_limits_and_strict_json() -> None:
    with pytest.raises(UnsafeTaskPayloadError, match="exceeds"):
        encode_task_arguments(["x" * MAX_TASK_ARGUMENT_BYTES], {})
    with pytest.raises(UnsafeTaskPayloadError, match="Invalid JSON constant"):
        decode_task_arguments(b"[NaN]", b"{}")
    with pytest.raises(UnsafeTaskPayloadError, match="Duplicate"):
        decode_task_arguments(b"[]", b'{"key":1,"key":2}')


def test_result_payload_is_json_not_executable_objects() -> None:
    encoded = encode_task_result({"value": 3, "items": [True, None]})
    assert decode_task_result(encoded) == {"value": 3, "items": [True, None]}
    with pytest.raises(UnsafeTaskPayloadError, match="JSON primitives"):
        encode_task_result(object())


def test_api_and_worker_modules_have_no_executable_decoder() -> None:
    paths = [
        Path("deepiri_zepgpu/api/server/routes/tasks.py"),
        Path("deepiri_zepgpu/api/server/routes/schedules.py"),
        Path("deepiri_zepgpu/api/server/routes/gang_scheduling.py"),
        Path("deepiri_zepgpu/queue/tasks.py"),
    ]
    forbidden_modules = {"pickle", "cloudpickle", "dill", "marshal"}
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            if names & forbidden_modules:
                violations.append(f"{path}: {sorted(names & forbidden_modules)}")
    assert violations == []
