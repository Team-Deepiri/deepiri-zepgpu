"""Regression tests for additive S3 endpoint configuration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deepiri_zepgpu.config import Settings, settings
from deepiri_zepgpu.storage import s3_client

pytestmark = pytest.mark.unit

LEGACY_ENDPOINT = "http://localhost:9000"
LEGACY_ACCESS_KEY = "minioadmin"
LEGACY_SECRET_KEY = "minioadmin"
LEGACY_REGION = "us-east-1"


@pytest.fixture(autouse=True)
def isolated_s3_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        *s3_client._AWS_ENDPOINT_ENV_VARS,
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_REGION",
        "S3__ENDPOINT_URL",
        "S3__ACCESS_KEY",
        "S3__SECRET_KEY",
        "S3__REGION",
        "ENDPOINT_URL",
        "ACCESS_KEY",
        "SECRET_KEY",
        "REGION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings.s3, "endpoint_url", LEGACY_ENDPOINT)
    monkeypatch.setattr(settings.s3, "access_key", LEGACY_ACCESS_KEY)
    monkeypatch.setattr(settings.s3, "secret_key", LEGACY_SECRET_KEY)
    monkeypatch.setattr(settings.s3, "region", LEGACY_REGION)


def _connect_with_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    client_factory = MagicMock(return_value=client)
    resource_factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(s3_client.boto3, "client", client_factory)
    monkeypatch.setattr(s3_client.boto3, "resource", resource_factory)

    s3_client.StorageClient().connect()
    return client_factory, resource_factory


def _assert_legacy_connection(factory: MagicMock, *, client: bool) -> None:
    args, kwargs = factory.call_args
    assert args == ("s3",)
    assert kwargs["endpoint_url"] == LEGACY_ENDPOINT
    assert kwargs["aws_access_key_id"] == LEGACY_ACCESS_KEY
    assert kwargs["aws_secret_access_key"] == LEGACY_SECRET_KEY
    assert kwargs["region_name"] == LEGACY_REGION
    if client:
        config = kwargs.pop("config")
        assert config.signature_version == "s3v4"
        assert config.retries == {"max_attempts": 3, "mode": "standard"}
        assert config.s3 is None
        assert config.connect_timeout == 60
        assert config.read_timeout == 60
    assert set(kwargs) == {
        "endpoint_url",
        "aws_access_key_id",
        "aws_secret_access_key",
        "region_name",
    }


def test_legacy_no_new_config_matches_origin_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    client_factory, resource_factory = _connect_with_mocks(monkeypatch)

    _assert_legacy_connection(client_factory, client=True)
    _assert_legacy_connection(resource_factory, client=False)


def test_s3_endpoint_url_behavior_matches_origin_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://ignored.example")

    configured = Settings(_env_file=None)
    client_factory, resource_factory = _connect_with_mocks(monkeypatch)

    assert configured.s3.endpoint_url == LEGACY_ENDPOINT
    assert client_factory.call_args.kwargs["endpoint_url"] == LEGACY_ENDPOINT
    assert resource_factory.call_args.kwargs["endpoint_url"] == LEGACY_ENDPOINT


def test_nested_s3_endpoint_url_remains_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3__ENDPOINT_URL", "http://configured-minio.example")
    configured = Settings(_env_file=None)
    monkeypatch.setattr(settings.s3, "endpoint_url", configured.s3.endpoint_url)

    client_factory, resource_factory = _connect_with_mocks(monkeypatch)

    assert client_factory.call_args.kwargs["endpoint_url"] == "http://configured-minio.example"
    assert client_factory.call_args.kwargs["config"].s3 is None
    assert resource_factory.call_args.kwargs["endpoint_url"] == "http://configured-minio.example"
    assert "config" not in resource_factory.call_args.kwargs


def test_nested_s3_credentials_remain_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3__ACCESS_KEY", "configured-access")
    monkeypatch.setenv("S3__SECRET_KEY", "configured-secret")
    configured = Settings(_env_file=None)
    monkeypatch.setattr(settings.s3, "access_key", configured.s3.access_key)
    monkeypatch.setattr(settings.s3, "secret_key", configured.s3.secret_key)

    client_factory, resource_factory = _connect_with_mocks(monkeypatch)

    for factory in (client_factory, resource_factory):
        assert factory.call_args.kwargs["aws_access_key_id"] == "configured-access"
        assert factory.call_args.kwargs["aws_secret_access_key"] == "configured-secret"


def test_generic_aws_endpoint_overrides_legacy_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4566")

    client_factory, resource_factory = _connect_with_mocks(monkeypatch)

    for factory in (client_factory, resource_factory):
        kwargs = factory.call_args.kwargs
        assert kwargs["endpoint_url"] == "http://localhost:4566"
        assert kwargs["aws_access_key_id"] == LEGACY_ACCESS_KEY
        assert kwargs["aws_secret_access_key"] == LEGACY_SECRET_KEY
        assert kwargs["region_name"] == LEGACY_REGION


def test_service_specific_aws_endpoint_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://generic.example")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://sdk-s3.example")

    client_factory, _ = _connect_with_mocks(monkeypatch)
    assert client_factory.call_args.kwargs["endpoint_url"] == "http://sdk-s3.example"

    monkeypatch.setenv("AWS_S3_ENDPOINT_URL", "http://zepgpu-s3.example")
    client_factory, _ = _connect_with_mocks(monkeypatch)
    assert client_factory.call_args.kwargs["endpoint_url"] == "http://zepgpu-s3.example"


def test_aws_endpoint_enables_path_style_and_short_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4566")

    client_factory, resource_factory = _connect_with_mocks(monkeypatch)

    client_config = client_factory.call_args.kwargs["config"]
    resource_config = resource_factory.call_args.kwargs["config"]
    assert client_config is resource_config
    assert client_config.s3 == {"addressing_style": "path"}
    assert client_config.connect_timeout == 2
    assert client_config.read_timeout == 5


def test_existing_real_aws_configuration_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.s3, "endpoint_url", "https://s3.us-west-2.amazonaws.com")
    monkeypatch.setattr(settings.s3, "access_key", "real-configuration-access")
    monkeypatch.setattr(settings.s3, "secret_key", "real-configuration-secret")
    monkeypatch.setattr(settings.s3, "region", "us-west-2")

    client_factory, resource_factory = _connect_with_mocks(monkeypatch)

    for factory in (client_factory, resource_factory):
        kwargs = factory.call_args.kwargs
        assert kwargs["endpoint_url"] == "https://s3.us-west-2.amazonaws.com"
        assert kwargs["aws_access_key_id"] == "real-configuration-access"
        assert kwargs["aws_secret_access_key"] == "real-configuration-secret"
        assert kwargs["region_name"] == "us-west-2"
    assert client_factory.call_args.kwargs["config"].s3 is None
    assert "config" not in resource_factory.call_args.kwargs
