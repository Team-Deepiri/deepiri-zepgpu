"""SSRF regression tests for task callback submission and delivery."""

from __future__ import annotations

import inspect
import ipaddress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepiri_zepgpu.api.server.routes import gang_scheduling, schedules, tasks
from deepiri_zepgpu.queue import tasks as worker_tasks
from deepiri_zepgpu.security import callbacks
from deepiri_zepgpu.security.callbacks import (
    CallbackDeliveryError,
    CallbackURLValidationError,
    deliver_callback,
    validate_callback_url,
)

PUBLIC_ADDRESS = ipaddress.ip_address("93.184.216.34")


def _set_dns(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> AsyncMock:
    resolver = AsyncMock(return_value=tuple(ipaddress.ip_address(value) for value in addresses))
    monkeypatch.setattr(callbacks, "resolve_callback_addresses", resolver)
    return resolver


@pytest.mark.asyncio
async def test_valid_allowlisted_https_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = _set_dns(monkeypatch, str(PUBLIC_ADDRESS))

    result = await validate_callback_url(
        "https://callbacks.example.com/hook",
        allowed_hosts=("callbacks.example.com",),
        environment="production",
    )

    assert result == "https://callbacks.example.com/hook"
    resolver.assert_awaited_once_with("callbacks.example.com", 443)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "https://",
        "https://bad host/hook",
        "https://example.com:99999/hook",
        "https://example.com/hook#fragment",
    ],
)
async def test_malformed_callback_urls_are_rejected(url: str) -> None:
    with pytest.raises(CallbackURLValidationError):
        await validate_callback_url(url, allowed_hosts=())


@pytest.mark.asyncio
async def test_unsupported_scheme_and_embedded_credentials_are_rejected() -> None:
    with pytest.raises(CallbackURLValidationError, match="scheme"):
        await validate_callback_url("ftp://example.com/hook", allowed_hosts=())
    with pytest.raises(CallbackURLValidationError, match="credentials"):
        await validate_callback_url(
            "https://user:secret@example.com/hook",
            allowed_hosts=(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "http://[::1]/hook",
        "http://10.0.0.1/hook",
        "http://172.16.0.1/hook",
        "http://192.168.1.1/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://[fd00::1]/hook",
        "http://[fe80::1]/hook",
        "http://[::ffff:192.168.1.2]/hook",
        "http://[64:ff9b::a9fe:a9fe]/latest/meta-data",
        "http://[64:ff9b::7f00:1]/hook",
        "http://[64:ff9b::a00:1]/hook",
        "http://0.0.0.0/hook",
        "http://224.0.0.1/hook",
        "http://240.0.0.1/hook",
    ],
)
async def test_non_public_literal_addresses_are_rejected(url: str) -> None:
    with pytest.raises(CallbackURLValidationError, match="prohibited"):
        await validate_callback_url(url, allowed_hosts=())


@pytest.mark.asyncio
async def test_localhost_requires_explicit_development_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dns(monkeypatch, "127.0.0.1")
    with pytest.raises(CallbackURLValidationError, match="localhost"):
        await validate_callback_url("http://localhost:9000/hook", allowed_hosts=())

    assert (
        await validate_callback_url(
            "http://localhost:9000/hook",
            allowed_hosts=(),
            allow_localhost=True,
            environment="development",
        )
        == "http://localhost:9000/hook"
    )

    with pytest.raises(CallbackURLValidationError):
        await validate_callback_url(
            "http://localhost:9000/hook",
            allowed_hosts=(),
            allow_localhost=True,
            environment="production",
        )


@pytest.mark.asyncio
async def test_dns_private_and_mixed_answers_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dns(monkeypatch, "10.0.0.4")
    with pytest.raises(CallbackURLValidationError, match="private"):
        await validate_callback_url(
            "https://callbacks.example.com",
            allowed_hosts=(),
        )

    _set_dns(monkeypatch, str(PUBLIC_ADDRESS), "192.168.1.7")
    with pytest.raises(CallbackURLValidationError, match="private"):
        await validate_callback_url(
            "https://callbacks.example.com",
            allowed_hosts=(),
        )


@pytest.mark.asyncio
async def test_dns_nat64_embedded_link_local_answer_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dns(monkeypatch, "64:ff9b::a9fe:a9fe")

    with pytest.raises(CallbackURLValidationError, match="prohibited"):
        await validate_callback_url(
            "https://callbacks.example.com/hook",
            allowed_hosts=(),
        )


@pytest.mark.asyncio
async def test_callback_allowlist_rejects_unlisted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = _set_dns(monkeypatch, str(PUBLIC_ADDRESS))
    with pytest.raises(
        CallbackURLValidationError,
        match="TASK_CALLBACK_ALLOWED_HOSTS",
    ):
        await validate_callback_url(
            "https://unlisted.example.com/hook",
            allowed_hosts=("callbacks.example.com",),
        )
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_production_callbacks_require_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = _set_dns(monkeypatch, str(PUBLIC_ADDRESS))
    with pytest.raises(CallbackURLValidationError, match="https"):
        await validate_callback_url(
            "http://callbacks.example.com/hook",
            allowed_hosts=("callbacks.example.com",),
            environment="production",
        )
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_any_3xx_response_is_rejected_without_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dns(monkeypatch, str(PUBLIC_ADDRESS))
    client_options: dict[str, object] = {}
    requests: list[tuple[str, str, dict[str, object]]] = []

    class FakeResponse:
        status_code = 302
        is_redirect = False

        def raise_for_status(self) -> None:
            raise AssertionError("3xx response must be rejected first")

    class FakeStream:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            client_options.update(kwargs)

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            **kwargs: object,
        ) -> FakeStream:
            requests.append((method, url, kwargs))
            return FakeStream()

    monkeypatch.setattr(callbacks.httpx, "AsyncClient", FakeClient)

    with pytest.raises(CallbackDeliveryError, match="redirect"):
        await deliver_callback(
            "https://callbacks.example.com/hook",
            {"task_id": "task-1"},
        )

    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert requests == [
        (
            "POST",
            "https://callbacks.example.com/hook",
            {"json": {"task_id": "task-1"}},
        )
    ]


@pytest.mark.asyncio
async def test_delivery_revalidates_dns_and_blocks_rebinding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(
        side_effect=[
            (PUBLIC_ADDRESS,),
            (ipaddress.ip_address("127.0.0.1"),),
        ]
    )
    monkeypatch.setattr(callbacks, "resolve_callback_addresses", resolver)
    client = AsyncMock()
    monkeypatch.setattr(callbacks.httpx, "AsyncClient", client)

    await validate_callback_url(
        "https://callbacks.example.com/hook",
        allowed_hosts=(),
    )
    with pytest.raises(CallbackURLValidationError, match="loopback"):
        await deliver_callback(
            "https://callbacks.example.com/hook",
            {"task_id": "task-1"},
        )

    assert resolver.await_count == 2
    client.assert_not_called()


@pytest.mark.asyncio
async def test_worker_callback_failure_is_recorded_without_escaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery = AsyncMock(side_effect=CallbackDeliveryError("redirect blocked"))
    monkeypatch.setattr(worker_tasks, "deliver_callback", delivery)
    resource = SimpleNamespace(
        callback_url="https://callbacks.example.com/hook",
        metadata_json={"existing": True},
    )

    delivered = await worker_tasks._deliver_and_record_callback(
        resource,
        resource_label="task",
        resource_id="task-1",
        status="completed",
        payload={"task_id": "task-1", "status": "completed"},
    )

    assert delivered is False
    assert resource.metadata_json["existing"] is True
    assert resource.metadata_json["callback_delivery"]["status"] == "failed"
    assert resource.metadata_json["callback_delivery"]["reason"] == "redirect blocked"


def test_all_callback_capable_submission_routes_use_shared_validation() -> None:
    route_functions = (
        tasks.create_task,
        schedules.create_schedule,
        schedules.update_schedule,
        schedules.create_delayed_task,
        gang_scheduling.create_gang_task,
    )
    for route_function in route_functions:
        assert "await validate_submitted_callback" in inspect.getsource(route_function)
