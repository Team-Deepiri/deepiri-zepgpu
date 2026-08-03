from uuid import uuid4

from deepiri_zepgpu.rooms.models import RoomConnectionConfigResponse


def test_room_connection_config_response_includes_auth_token() -> None:
    room_id = uuid4()
    peer_id = uuid4()

    response = RoomConnectionConfigResponse(
        room_id=room_id,
        peer_id=peer_id,
        config="[Interface]\nPrivateKey = test",
        filename="room.conf",
        auth_token="room-scoped-token",
    )

    assert response.room_id == room_id
    assert response.peer_id == peer_id
    assert response.auth_token == "room-scoped-token"

    serialized = response.model_dump()

    assert serialized["auth_token"] == "room-scoped-token"


def test_room_connection_config_response_allows_missing_auth_token() -> None:
    response = RoomConnectionConfigResponse(
        room_id=uuid4(),
        peer_id=uuid4(),
        config="[Interface]\nPrivateKey = test",
        filename="room.conf",
    )

    assert response.auth_token is None
    assert response.model_dump()["auth_token"] is None


def test_auth_token_has_openapi_description() -> None:
    schema = RoomConnectionConfigResponse.model_json_schema()
    auth_token_schema = schema["properties"]["auth_token"]

    assert "description" in auth_token_schema
    assert "Room-scoped provider authentication token" in auth_token_schema["description"]
    assert "secret" in auth_token_schema["description"].lower()
