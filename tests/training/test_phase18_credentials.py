"""Regression tests for Phase 18 short-lived credential refresh."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from deepiri_zepgpu.node_agent import training_runner as training_runner_module
from deepiri_zepgpu.training import process_worker as process_worker_module
from deepiri_zepgpu.training.worker import HttpWorkerCoordinator, WorkerEvent


class _RefreshResponse:
    status_code = 200

    def json(self) -> dict[str, str]:
        return {"credential": "refreshed-run-credential"}

    def raise_for_status(self) -> None:
        return None


class _RefreshClient:
    requests: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def __aenter__(self) -> _RefreshClient:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    async def post(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        **kwargs: Any,
    ) -> _RefreshResponse:
        del kwargs
        self.requests.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
            }
        )
        return _RefreshResponse()


@pytest.mark.asyncio
async def test_refresh_updates_all_rank_credential_files_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One provider refresh must install the same token for every local rank."""

    rank_zero = tmp_path / "process-0"
    rank_one = tmp_path / "process-1"
    rank_zero.mkdir()
    rank_one.mkdir()

    credential_paths = [
        rank_zero / "run.cred",
        rank_one / "run.cred",
    ]

    for path in credential_paths:
        path.write_text("original-run-credential", encoding="utf-8")

    runner = training_runner_module.TrainingAgentRunner(provider_token="provider-token")

    _RefreshClient.requests.clear()
    monkeypatch.setattr(
        training_runner_module.httpx,
        "AsyncClient",
        _RefreshClient,
    )

    sleep_calls = 0

    async def fake_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1

        assert delay == 600.0

        # First sleep allows exactly one refresh to execute. The second
        # iteration stops the otherwise long-lived refresh loop.
        if sleep_calls > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(
        training_runner_module.asyncio,
        "sleep",
        fake_sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await runner._refresh_run_credential_loop(
            run_id="run-1",
            worker_id="worker-1",
            peer_id="provider-1",
            base_url="http://coordinator",
            credential_paths=credential_paths,
        )

    assert rank_zero.joinpath("run.cred").read_text(encoding="utf-8") == "refreshed-run-credential"

    assert rank_one.joinpath("run.cred").read_text(encoding="utf-8") == "refreshed-run-credential"

    # Atomic replacement should not leave temporary credential files behind.
    assert not rank_zero.joinpath("run.cred.tmp").exists()
    assert not rank_one.joinpath("run.cred.tmp").exists()

    assert len(_RefreshClient.requests) == 1
    request = _RefreshClient.requests[0]

    assert request["url"].endswith("/api/v1/training-runs/run-1/workers/worker-1/credential")
    assert request["params"] == {"peer_id": "provider-1"}
    assert request["headers"]["Authorization"] == "Bearer provider-token"


@pytest.mark.asyncio
async def test_http_worker_coordinator_uses_latest_dynamic_credential() -> None:
    """Heartbeat/event calls must not keep using the credential from startup."""

    credential = {"value": "credential-a"}
    authorization_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers["Authorization"])

        if request.method == "GET":
            return httpx.Response(
                200,
                json={"run_state": "running"},
            )

        if request.method == "POST":
            return httpx.Response(200, json={})

        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        coordinator = HttpWorkerCoordinator(
            base_url="http://coordinator",
            run_id="run-1",
            peer_id="provider-1",
            client=client,
            authorization_getter=lambda: credential["value"],
        )

        await coordinator.authenticate(
            worker_id="worker-1",
            provider_token="provider-token",
            run_credential="credential-a",
        )

        # Simulate the provider agent replacing run.cred after refresh.
        credential["value"] = "credential-b"

        await coordinator.event(
            "worker-1",
            WorkerEvent(
                event_id="event-1",
                kind="heartbeat",
                timestamp=datetime.now(UTC),
                payload={"state": "ready"},
            ),
        )

    assert authorization_headers == [
        "Bearer credential-a",
        "Bearer credential-b",
    ]


class _FakeDiLoCoRuntime:
    def initial_state_envelope(self) -> bytes:
        return b"initial-state"


@pytest.mark.asyncio
async def test_phase18_requests_reread_run_credential(
    tmp_path: Path,
) -> None:
    """Phase 18 HTTP helpers must consume the current run.cred contents."""

    work_dir = tmp_path / "worker"
    work_dir.mkdir()

    credential_path = work_dir / "run.cred"
    credential_path.write_text("credential-a", encoding="utf-8")

    authorization_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers["Authorization"])

        return httpx.Response(
            200,
            json={
                "bootstrap_required": False,
            },
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        await process_worker_module._phase18_register(
            client,
            base_url="http://coordinator",
            run_id="run-1",
            worker_id="worker-1",
            peer_id="provider-1",
            work_dir=work_dir,
            runtime=_FakeDiLoCoRuntime(),
        )

        # Simulate TrainingAgentRunner refreshing the file without restarting
        # this worker process.
        credential_path.write_text("credential-b", encoding="utf-8")

        await process_worker_module._phase18_register(
            client,
            base_url="http://coordinator",
            run_id="run-1",
            worker_id="worker-1",
            peer_id="provider-1",
            work_dir=work_dir,
            runtime=_FakeDiLoCoRuntime(),
        )

    assert authorization_headers == [
        "Bearer credential-a",
        "Bearer credential-b",
    ]


class _FailureResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


class _FailureClient:
    requests: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def __aenter__(self) -> _FailureClient:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    async def post(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        json: dict[str, Any],
        **kwargs: Any,
    ) -> _FailureResponse:
        del kwargs

        self.requests.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "json": json,
            }
        )
        return _FailureResponse()


@pytest.mark.asyncio
async def test_provider_supervisor_failure_uses_provider_token_and_no_fake_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supervisor fallback must survive an expired run credential."""

    runner = training_runner_module.TrainingAgentRunner(provider_token="persistent-provider-token")

    _FailureClient.requests.clear()

    monkeypatch.setattr(
        training_runner_module.httpx,
        "AsyncClient",
        _FailureClient,
    )

    await runner._report_failure(
        run_id="run-1",
        worker_id="worker-1",
        peer_id="provider-1",
        base_url="http://coordinator",
        error="child process exited unexpectedly",
    )

    assert len(_FailureClient.requests) == 1

    request = _FailureClient.requests[0]

    assert request["headers"]["Authorization"] == ("Bearer persistent-provider-token")

    assert request["params"] == {"peer_id": "provider-1"}

    body = request["json"]
    assert body["kind"] == "round_failed"

    # The parent process supervisor does not know the exact active outer
    # round, so it must not invent one such as round=1.
    assert "round" not in body["payload"]

    assert body["payload"]["source"] == "provider_process_supervisor"
    assert body["payload"]["error_type"] == "child process exited unexpectedly"
