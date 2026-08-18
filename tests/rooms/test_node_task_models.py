"""Tests for node task assignment models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from deepiri_zepgpu.database.models.node_task_assignment import (
    NodeAssignmentStatus,
    NodeTaskAssignment,
    NodeTaskEvent,
)


def test_assignment_status_values() -> None:
    assert NodeAssignmentStatus.ASSIGNED.value == "assigned"
    assert NodeAssignmentStatus.ACCEPTED.value == "accepted"
    assert NodeAssignmentStatus.RUNNING.value == "running"
    assert NodeAssignmentStatus.COMPLETED.value == "completed"
    assert NodeAssignmentStatus.FAILED.value == "failed"
    assert NodeAssignmentStatus.CANCELLED.value == "cancelled"


def test_terminal_reason_values() -> None:
    from deepiri_zepgpu.database.models.node_task_assignment import NodeTerminalReason

    assert NodeTerminalReason.LEASE_EXPIRED.value == "lease_expired"
    assert NodeTerminalReason.ACCEPTED_TIMEOUT.value == "accepted_timeout"
    assert NodeTerminalReason.RUNNING_TIMEOUT.value == "running_timeout"


def test_assignment_model_fields() -> None:
    now = datetime.now(UTC)
    assignment = NodeTaskAssignment(
        id=str(uuid4()),
        vpn_network_id=str(uuid4()),
        task_id=str(uuid4()),
        peer_id=str(uuid4()),
        gpu_share_id=str(uuid4()),
        status=NodeAssignmentStatus.ASSIGNED,
        assigned_at=now,
        claim_generation=0,
        retry_count=0,
    )
    assert assignment.status == NodeAssignmentStatus.ASSIGNED
    assert assignment.retry_count == 0
    assert assignment.assigned_at == now
    assert assignment.claim_generation == 0
    assert assignment.claimed_at is None
    assert assignment.lease_expires_at is None
    assert assignment.terminal_reason is None


def test_assignment_failed_state_fields() -> None:
    now = datetime.now(UTC)
    assignment = NodeTaskAssignment(
        id=str(uuid4()),
        vpn_network_id=str(uuid4()),
        task_id=str(uuid4()),
        peer_id=str(uuid4()),
        gpu_share_id=str(uuid4()),
        status=NodeAssignmentStatus.FAILED,
        assigned_at=now,
        failed_at=now,
        error="lock timeout",
        retry_count=2,
    )
    assert assignment.failed_at == now
    assert assignment.error == "lock timeout"
    assert assignment.retry_count == 2


def test_event_model_fields() -> None:
    now = datetime.now(UTC)
    event = NodeTaskEvent(
        id=str(uuid4()),
        assignment_id=str(uuid4()),
        event_type="assignment_created",
        payload={"task_id": "abc"},
        created_at=now,
    )
    assert event.event_type == "assignment_created"
    assert event.payload == {"task_id": "abc"}
