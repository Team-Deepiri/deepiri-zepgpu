"""Full-system API regression against Postgres (post compute-ledger integration)."""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.integration]


@pytest.mark.asyncio
async def test_health_ready_live_root_metrics(regression_client):
    root = await regression_client.get("/")
    assert root.status_code == 200
    assert root.json()["status"] == "running"

    health = await regression_client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "healthy"
    assert "version" in body

    ready = await regression_client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True

    live = await regression_client.get("/api/v1/health/live")
    assert live.status_code == 200
    assert live.json()["alive"] is True

    metrics = await regression_client.get("/metrics")
    assert metrics.status_code == 200
    assert "zepgpu_http_requests_total" in metrics.text or metrics.text.startswith("#")


@pytest.mark.asyncio
async def test_auth_register_login_me(anonymous_client):
    suffix = uuid.uuid4().hex[:8]
    username = f"reguser_{suffix}"
    email = f"reguser_{suffix}@example.com"
    password = "securepass1"

    registered = await anonymous_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "first_name": "Reg",
            "last_name": "User",
        },
    )
    assert registered.status_code == 201, registered.text
    user = registered.json()
    assert user["username"] == username
    assert user["id"]

    login = await anonymous_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert token

    me = await anonymous_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["username"] == username


@pytest.mark.asyncio
async def test_tasks_create_list_get(regression_client):
    created = await regression_client.post(
        "/api/v1/tasks",
        json={
            "name": "regression-task",
            "func_name": "math.sqrt",
            "priority": 2,
            "gpu_memory_mb": 512,
            "timeout_seconds": 60,
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    task_id = task["id"]
    assert task["status"] == "pending"

    listed = await regression_client.get("/api/v1/tasks")
    assert listed.status_code == 200, listed.text
    ids = {t["id"] for t in listed.json()["tasks"]}
    assert task_id in ids

    got = await regression_client.get(f"/api/v1/tasks/{task_id}")
    assert got.status_code == 200, got.text
    assert got.json()["name"] == "regression-task"


@pytest.mark.asyncio
async def test_gpu_devices_and_stats(regression_client):
    devices = await regression_client.get("/api/v1/gpu/devices")
    assert devices.status_code == 200, devices.text
    body = devices.json()
    assert "devices" in body
    assert "total_count" in body

    stats = await regression_client.get("/api/v1/gpu/stats")
    assert stats.status_code == 200, stats.text


@pytest.mark.asyncio
async def test_namespace_create_list(regression_client):
    name = f"ns-{uuid.uuid4().hex[:8]}"
    created = await regression_client.post(
        "/api/v1/namespaces",
        json={"name": name, "display_name": "Regression NS"},
    )
    assert created.status_code == 201, created.text
    ns_id = created.json()["id"]

    listed = await regression_client.get("/api/v1/namespaces")
    assert listed.status_code == 200, listed.text
    ids = {
        n["id"]
        for n in listed.json().get(
            "namespaces", listed.json() if isinstance(listed.json(), list) else []
        )
    }
    # NamespaceListResponse uses namespaces key
    payload = listed.json()
    if "namespaces" in payload:
        ids = {n["id"] for n in payload["namespaces"]}
    assert ns_id in ids


@pytest.mark.asyncio
async def test_schedule_create_list(regression_client):
    created = await regression_client.post(
        "/api/v1/schedules",
        json={
            "name": "regression-interval",
            "schedule_type": "interval",
            "interval_seconds": 120,
            "func_name": "math.sqrt",
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]

    listed = await regression_client.get("/api/v1/schedules")
    assert listed.status_code == 200, listed.text
    ids = {s["id"] for s in listed.json()["schedules"]}
    assert schedule_id in ids


@pytest.mark.asyncio
async def test_pipeline_create_list(regression_client):
    created = await regression_client.post(
        "/api/v1/pipelines",
        json={
            "name": "regression-pipeline",
            "description": "system regression",
            "stages": [
                {"name": "stage-a", "func_name": "math.sqrt", "args": {}},
            ],
        },
    )
    assert created.status_code == 201, created.text
    pipeline_id = created.json()["id"]

    listed = await regression_client.get("/api/v1/pipelines")
    assert listed.status_code == 200, listed.text
    ids = {p["id"] for p in listed.json()["pipelines"]}
    assert pipeline_id in ids


@pytest.mark.asyncio
async def test_vpn_networks_list_smoke(regression_client):
    resp = await regression_client.get("/api/v1/vpn/networks")
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_cloud_providers_and_health_smoke(regression_client):
    providers = await regression_client.get("/api/v1/cloud/providers")
    assert providers.status_code == 200, providers.text

    health = await regression_client.get("/api/v1/cloud/health")
    assert health.status_code == 200, health.text


@pytest.mark.asyncio
async def test_ledger_still_works_after_system_writes(regression_client):
    """Ledger must remain healthy after other modules write to the shared DB."""
    # Touch another module first
    await regression_client.post(
        "/api/v1/tasks",
        json={"name": "pre-ledger", "func_name": "math.sqrt"},
    )

    status = await regression_client.get("/api/v1/ledger/status")
    assert status.status_code == 200, status.text
    assert status.json()["enabled"] is True

    attest = await regression_client.post(
        "/api/v1/ledger/attestations/job-completed",
        json={
            "task_id": "reg-ledger-1",
            "provider_account": "prov",
            "consumer_account": "cons",
            "gpu_seconds": 2.5,
        },
    )
    assert attest.status_code == 200, attest.text
    assert attest.json()["block"]["finalized"] is True

    verify = await regression_client.get("/api/v1/ledger/verify")
    assert verify.status_code == 200
    assert verify.json()["valid"] is True

    balances = await regression_client.get("/api/v1/ledger/balances")
    assert balances.status_code == 200
    accounts = {b["account"]: b for b in balances.json()}
    assert accounts["prov"]["credit_seconds"] == 2.5


@pytest.mark.asyncio
async def test_gang_list_and_fair_share_smoke(regression_client):
    gangs = await regression_client.get("/api/v1/gang/gang")
    assert gangs.status_code == 200, gangs.text

    fair = await regression_client.get("/api/v1/gang/fair-share/me")
    assert fair.status_code in (200, 404), fair.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/v1/tasks",
            {"name": "blocked-callback", "func_name": "math.sqrt", "args": [0]},
        ),
        (
            "/api/v1/schedules",
            {
                "name": "blocked-scheduled-callback",
                "schedule_type": "interval",
                "interval_seconds": 120,
                "func_name": "math.sqrt",
                "args": [0],
            },
        ),
        (
            "/api/v1/gang/gang",
            {
                "name": "blocked-gang-callback",
                "num_gpus_required": 2,
                "func_name": "math.sqrt",
                "args": [0],
            },
        ),
    ],
)
async def test_all_task_submission_types_reject_private_callbacks(
    regression_client,
    path: str,
    payload: dict[str, object],
) -> None:
    response = await regression_client.post(
        path,
        json={**payload, "callback_url": "http://127.0.0.1/hook"},
    )
    assert response.status_code == 422, response.text
    assert "Invalid callback URL" in response.json()["detail"]
