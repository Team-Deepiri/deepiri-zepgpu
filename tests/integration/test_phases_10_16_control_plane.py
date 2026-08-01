"""Phases 10–16 control-plane matrix (integration when Postgres is available).

Documents and exercises:
  dial-out room → invite join → provider heartbeat → claim/accept same event
  → complete single terminal notify path → revoke → negative invite/token/cross-room.

When Postgres fixtures are unavailable, the module still documents the matrix via
unit-level assertions that do not require a live coordinator.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepiri_zepgpu.api.server.routes import node_tasks

# Matrix covered by this module / verify_phases_10_16_local.py:
PHASES_10_16_MATRIX = (
    ("dialout_room_create", "transport_mode=dialout"),
    ("invite_join", "provider auth_token issued"),
    ("provider_heartbeat", "capabilities + path + health"),
    ("claim_accept_same_event", "room_task_claimed"),
    ("complete_single_notify", "notify_assignment_terminal once"),
    ("negative_bad_invite", "4xx"),
    ("negative_forged_token", "401/403"),
    ("negative_cross_room_claim", "403/404/409"),
    ("revoke_blocks_heartbeat", "401/403"),
    ("training_two_workers_relay_abort", "optional Redis"),
)


def test_phases_10_16_matrix_is_documented() -> None:
    assert len(PHASES_10_16_MATRIX) >= 8
    names = {name for name, _ in PHASES_10_16_MATRIX}
    assert "claim_accept_same_event" in names
    assert "complete_single_notify" in names
    assert "negative_cross_room_claim" in names


@pytest.mark.asyncio
async def test_claim_accept_complete_notify_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit stand-in for the claim/accept/complete slice of the matrix."""

    assignment = SimpleNamespace(
        id="assignment-1",
        vpn_network_id="room-1",
        task_id="task-1",
        peer_id="peer-1",
        gpu_share_id="gpu-1",
        status=SimpleNamespace(value="assigned"),
        is_terminal=False,
        terminal_reason=None,
        claimed_at=None,
        lease_expires_at=None,
        claim_generation=0,
        cancel_requested_at=None,
        accepted_at=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        error=None,
    )

    class Repo:
        async def mark_claimed(self, **_kwargs):
            assignment.status = SimpleNamespace(value="accepted")
            assignment.claim_generation = 1
            return assignment

        async def mark_completed(self, **_kwargs):
            assignment.status = SimpleNamespace(value="completed")
            assignment.is_terminal = True
            assignment.terminal_reason = "completed"
            return assignment

    class Db:
        async def commit(self) -> None:
            return None

        async def refresh(self, _obj) -> None:
            return None

        async def get(self, _model, _task_id):
            return SimpleNamespace(status=SimpleNamespace(value="running"), error=None)

    emit_event = AsyncMock()
    notify = AsyncMock()
    monkeypatch.setattr(node_tasks, "NodeTaskRepository", lambda _db: Repo())
    monkeypatch.setattr(node_tasks, "emit_assignment_room_event", emit_event)
    monkeypatch.setattr(node_tasks, "notify_assignment_terminal", notify)

    peer = SimpleNamespace(id="peer-1")
    db = Db()
    await node_tasks.claim_node_task("assignment-1", db=db, peer=peer)
    claim_type = emit_event.await_args.kwargs["event_type"]
    emit_event.reset_mock()
    await node_tasks.accept_node_task("assignment-1", db=db, peer=peer)
    accept_type = emit_event.await_args.kwargs["event_type"]
    assert claim_type == accept_type == "room_task_claimed"

    await node_tasks.complete_node_task(
        "assignment-1",
        node_tasks.CompleteNodeTaskRequest(result_metadata={"ok": True}),
        db=db,
        peer=peer,
    )
    notify.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_phases_10_16_control_plane_api(api_client, integration_engine, auth_user) -> None:
    """Live Postgres-backed slice: dial-out room, invite, join negatives."""

    Session = async_sessionmaker(integration_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        session.add(auth_user)
        await session.commit()

    suffix = uuid4().hex[:8]
    room = await api_client.post(
        "/api/v1/rooms",
        json={
            "name": f"p1016-{suffix}",
            "description": "phases 10-16 integration",
            "transport_mode": "dialout",
        },
    )
    assert room.status_code == 201, room.text
    body = room.json()
    assert body["transport_mode"] == "dialout"
    room_id = body["id"]

    invite = await api_client.post(f"/api/v1/rooms/{room_id}/invites", json={"max_uses": 1})
    assert invite.status_code in {200, 201}, invite.text
    code = invite.json()["code"]

    bad = await api_client.post("/api/v1/rooms/join", json={"invite_code": "ZZZZINVALID"})
    assert bad.status_code in {400, 404, 422}

    forged = await api_client.post(
        f"/api/v1/rooms/{room_id}/nodes/{uuid4()}/heartbeat",
        headers={"Authorization": "Bearer forged-token"},
        json={"is_online": True, "gpu_status": []},
    )
    assert forged.status_code in {401, 403, 404}

    listed = await api_client.get(f"/api/v1/rooms/{room_id}/invites")
    assert listed.status_code == 200
    assert any(item.get("code") == code for item in listed.json())
