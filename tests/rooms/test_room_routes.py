"""Tests for room route registration and authentication behavior."""

from __future__ import annotations

from fastapi.testclient import TestClient

from deepiri_zepgpu.api.server.main import app

client = TestClient(app)


def test_room_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/v1/rooms" in paths
    assert "/api/v1/rooms/{room_id}" in paths
    assert "/api/v1/rooms/{room_id}/members" in paths
    assert "/api/v1/rooms/{room_id}/members/me" in paths
    assert "/api/v1/rooms/{room_id}/gpu-pool" in paths
    assert "/api/v1/rooms/{room_id}/invites" in paths
    assert "/api/v1/rooms/{room_id}/invites/{invite_id}" in paths
    assert "/api/v1/rooms/join" in paths
    assert "/api/v1/rooms/{room_id}/config" in paths
    assert "/api/v1/rooms/{room_id}/nodes" in paths
    assert "/api/v1/rooms/{room_id}/nodes/{peer_id}" in paths
    assert "/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat" in paths
    assert "/api/v1/rooms/{room_id}/nodes/{peer_id}/gpus" in paths
    assert "/api/v1/rooms/{room_id}/gpus" in paths


def test_legacy_vpn_routes_remain_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/v1/vpn/networks" in paths
    assert "/api/v1/vpn/networks/{network_id}" in paths
    assert "/api/v1/vpn/networks/{network_id}/invite" in paths


def test_list_rooms_requires_authentication() -> None:
    response = client.get("/api/v1/rooms")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_create_room_requires_authentication() -> None:
    response = client.post("/api/v1/rooms", json={"name": "Test Room"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_get_room_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_delete_room_requires_authentication() -> None:
    response = client.delete("/api/v1/rooms/test-room-id")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_list_room_members_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/members")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_leave_room_requires_authentication() -> None:
    response = client.delete("/api/v1/rooms/test-room-id/members/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_get_room_gpu_pool_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/gpu-pool")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_create_room_invite_requires_authentication() -> None:
    response = client.post("/api/v1/rooms/test-room-id/invites", json={"max_uses": 1})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_list_room_invites_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/invites")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_revoke_room_invite_requires_authentication() -> None:
    response = client.delete("/api/v1/rooms/test-room-id/invites/test-invite-id")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_join_room_requires_authentication() -> None:
    response = client.post("/api/v1/rooms/join", json={"invite_code": "ABC123"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_get_room_config_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/config")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_list_room_nodes_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/nodes")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_get_room_node_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/nodes/test-peer-id")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_room_node_heartbeat_requires_authentication() -> None:
    response = client.post(
        "/api/v1/rooms/test-room-id/nodes/test-peer-id/heartbeat",
        json={"gpu_status": []},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_list_room_node_gpus_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/nodes/test-peer-id/gpus")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_list_room_gpus_requires_authentication() -> None:
    response = client.get("/api/v1/rooms/test-room-id/gpus")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
