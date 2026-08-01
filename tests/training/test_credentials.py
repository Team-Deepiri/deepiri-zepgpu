import time
import uuid

import pytest

from deepiri_zepgpu.training.credentials import (
    RunCredential,
    issue_run_credential,
    verify_run_credential,
)


def test_short_lived_run_credentials() -> None:
    credential = RunCredential(
        room_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        worker_id=str(uuid.uuid4()),
        peer_id=str(uuid.uuid4()),
        credential_id=str(uuid.uuid4()),
        expires_at=int(time.time()) + 60,
    )
    token = issue_run_credential(credential, b"coordinator-secret")
    assert verify_run_credential(token, b"coordinator-secret") == credential
    with pytest.raises(ValueError, match="invalid"):
        verify_run_credential(token, b"wrong-secret")
    with pytest.raises(ValueError, match="expired"):
        verify_run_credential(token, b"coordinator-secret", now=credential.expires_at + 1)
    with pytest.raises(ValueError, match="expired"):
        verify_run_credential(token, b"coordinator-secret", now=credential.expires_at)
    with pytest.raises(ValueError, match="malformed"):
        verify_run_credential(token + "!", b"coordinator-secret")
