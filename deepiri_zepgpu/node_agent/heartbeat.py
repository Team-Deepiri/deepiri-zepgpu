"""HTTP heartbeat client for room node registration."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from deepiri_zepgpu.node_agent.config import NodeAgentConfig
from deepiri_zepgpu.node_agent.gpu_reporter import collect_gpu_status

logger = logging.getLogger(__name__)

_TRANSIENT_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)


def build_heartbeat_payload(
    config: NodeAgentConfig,
    *,
    gpu_status: list[dict[str, Any]] | None = None,
    is_online: bool = True,
) -> dict[str, Any]:
    return {
        "gpu_status": (
            gpu_status
            if gpu_status is not None
            else collect_gpu_status(simulation_mode=config.simulation_mode)
        ),
        "is_online": is_online,
        "endpoint": config.endpoint,
    }


def heartbeat_url(config: NodeAgentConfig) -> str:
    return (
        f"{config.api_base_url}/api/v1/rooms/{config.room_id}" f"/nodes/{config.peer_id}/heartbeat"
    )


def _headers(config: NodeAgentConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.auth_token}",
        "Content-Type": "application/json",
    }


def redact_payload_for_log(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


@retry(
    retry=retry_if_exception_type(_TRANSIENT_ERRORS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _post_heartbeat(config: NodeAgentConfig, payload: dict[str, Any]) -> httpx.Response:
    response = httpx.post(
        heartbeat_url(config),
        json=payload,
        headers=_headers(config),
        timeout=30.0,
    )
    if response.status_code >= 500:
        response.raise_for_status()
    return response


def send_heartbeat(
    config: NodeAgentConfig,
    *,
    dry_run: bool = False,
    gpu_status: list[dict[str, Any]] | None = None,
    is_online: bool = True,
) -> dict[str, Any] | None:
    payload = build_heartbeat_payload(config, gpu_status=gpu_status, is_online=is_online)

    if dry_run:
        logger.info("Dry-run heartbeat to %s", heartbeat_url(config))
        logger.info("Payload:\n%s", redact_payload_for_log(payload))
        return None

    try:
        response = _post_heartbeat(config, payload)
    except httpx.HTTPError as exc:
        logger.error("Heartbeat failed: %s", exc)
        raise

    if response.status_code >= 400:
        detail = response.text
        logger.error("Heartbeat rejected (%s): %s", response.status_code, detail)
        response.raise_for_status()

    logger.info("Heartbeat accepted for peer %s (status %s)", config.peer_id, response.status_code)
    return cast(dict[str, Any], response.json())
