"""Opt-in S3 result-storage integration test for a running Floci instance."""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import uuid

import pytest

from deepiri_zepgpu.config import settings
from deepiri_zepgpu.storage.s3_client import StorageClient

pytestmark = [pytest.mark.integration, pytest.mark.floci]


def _floci_endpoint() -> str:
    endpoint = (
        os.getenv("AWS_S3_ENDPOINT_URL")
        or os.getenv("AWS_ENDPOINT_URL_S3")
        or os.getenv("AWS_ENDPOINT_URL")
    )
    if not endpoint:
        pytest.skip("Floci endpoint is not configured")

    health_url = f"{endpoint.rstrip('/')}/_floci/health"
    try:
        with urllib.request.urlopen(health_url, timeout=1.0) as response:
            if response.status != 200:
                pytest.skip(f"Floci health check returned HTTP {response.status}")
    except (OSError, urllib.error.URLError) as exc:
        pytest.skip(f"Floci is unavailable at {endpoint}: {exc}")
    return endpoint


def test_result_storage_round_trip_and_presigned_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = _floci_endpoint()
    bucket = f"zepgpu-floci-{uuid.uuid4().hex}"
    first_task = uuid.uuid4().hex
    second_task = uuid.uuid4().hex

    monkeypatch.setattr(settings.s3, "bucket_name", bucket)

    storage = StorageClient()
    storage.connect()
    assert storage._client is not None

    try:
        assert storage.upload_result(first_task, b"stored through ZepGPU", "text/plain") == (
            f"results/{first_task}"
        )
        assert storage.download_result(first_task) == b"stored through ZepGPU"
        assert storage.result_exists(first_task)
        assert storage.get_result_size(first_task) == len(b"stored through ZepGPU")
        assert {item["key"] for item in storage.list_results()} == {f"results/{first_task}"}

        get_url = storage.generate_presigned_url(first_task, expiry_seconds=30)
        assert get_url is not None and get_url.startswith(endpoint)
        with urllib.request.urlopen(get_url, timeout=2.0) as response:
            assert response.read() == b"stored through ZepGPU"

        put_url = storage.upload_presigned_put_url(second_task, expiry_seconds=30)
        assert put_url is not None and put_url.startswith(endpoint)
        request = urllib.request.Request(
            put_url,
            data=b"uploaded through a presigned URL",
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=2.0) as response:
            assert response.status == 200
        assert storage.download_result(second_task) == b"uploaded through a presigned URL"

        assert storage.delete_result(first_task)
        assert not storage.result_exists(first_task)
    finally:
        storage.delete_result(first_task)
        storage.delete_result(second_task)
        storage._client.delete_bucket(Bucket=bucket)
