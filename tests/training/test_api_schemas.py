import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from deepiri_zepgpu.api.server.main import app
from deepiri_zepgpu.api.server.routes.training_runs import (
    CreateTrainingRunRequest,
    _require_relay_worker,
    get_verified_training_peer,
)
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.training.credentials import RunCredential, issue_run_credential


def test_create_training_run_schema_rejects_duplicate_or_malformed_ids() -> None:
    room_id = uuid4()
    provider_id = uuid4()
    with pytest.raises(ValidationError, match="provider_ids must be unique"):
        CreateTrainingRunRequest(
            room_id=room_id,
            provider_ids=[provider_id, provider_id],
            config={},
        )
    with pytest.raises(ValidationError):
        CreateTrainingRunRequest(room_id="not-a-uuid", config={})


def test_training_run_api_surface_is_first_class() -> None:
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        if hasattr(route, "methods"):
            methods_by_path.setdefault(route.path, set()).update(route.methods)
    assert "POST" in methods_by_path["/api/v1/training-runs"]
    assert "GET" in methods_by_path["/api/v1/training-runs"]
    assert "GET" in methods_by_path["/api/v1/training-runs/{run_id}"]
    assert "POST" in methods_by_path["/api/v1/training-runs/{run_id}/start"]
    assert "POST" in methods_by_path["/api/v1/training-runs/{run_id}/abort"]
    assert "GET" in methods_by_path["/api/v1/training-runs/relay/{transfer_id}/payload"]


@pytest.mark.asyncio
async def test_relay_requires_peer_assignment_to_run() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    database = AsyncMock()
    database.execute.return_value = result
    peer = SimpleNamespace(id=uuid4())
    with pytest.raises(HTTPException) as error:
        await _require_relay_worker(database, peer, str(uuid4()), str(uuid4()))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_relay_accepts_scoped_short_lived_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    peer_id = uuid4()
    credential = RunCredential(
        room_id=str(uuid4()),
        run_id=str(uuid4()),
        worker_id=str(uuid4()),
        peer_id=str(peer_id),
        credential_id=str(uuid4()),
        expires_at=int(time.time()) + 60,
    )
    token = issue_run_credential(credential, settings.auth.secret_key.encode("utf-8"))
    provider_auth = AsyncMock(side_effect=HTTPException(status_code=401))
    monkeypatch.setattr(
        "deepiri_zepgpu.api.server.routes.training_runs.get_verified_peer", provider_auth
    )
    result = SimpleNamespace(scalar_one_or_none=lambda: object())
    peer = SimpleNamespace(id=peer_id)
    database = AsyncMock()
    database.execute.return_value = result
    database.get.return_value = peer
    authenticated = await get_verified_training_peer(
        peer_id=peer_id,
        authorization=f"Bearer {token}",
        db=database,
    )
    assert authenticated is peer
