"""HTTP heartbeat client for room node registration."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, cast

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from deepiri_zepgpu.node_agent.config import NodeAgentConfig
from deepiri_zepgpu.node_agent.gpu_reporter import (
    collect_capability_inventory,
    collect_gpu_status,
)
from deepiri_zepgpu.rooms.path_obs import (
    MEASUREMENT_MEASURED,
    PATH_TYPE_DIRECT,
    infer_path_class_from_rtt,
)

logger = logging.getLogger(__name__)

_TRANSIENT_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)

# Last measured provider↔coordinator RTT (ms), reported on the subsequent heartbeat.
_last_coordinator_rtt_ms: float | None = None


def build_heartbeat_payload(
    config: NodeAgentConfig,
    *,
    gpu_status: list[dict[str, Any]] | None = None,
    is_online: bool = True,
    coordinator_rtt_ms: float | None = None,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gpus = (
        gpu_status
        if gpu_status is not None
        else collect_gpu_status(simulation_mode=config.simulation_mode)
    )
    caps = capabilities
    if caps is None:
        caps = collect_capability_inventory(simulation_mode=config.simulation_mode)
        caps = {**caps, "gpus": gpus}

    payload: dict[str, Any] = {
        "gpu_status": gpus,
        "is_online": is_online,
        "endpoint": config.endpoint,
        "agent_version": config.agent_version,
        "node_name": config.node_name,
        "provider_mode": config.provider_mode,
        "capabilities": {
            "runtime": caps.get("runtime"),
            "topology": caps.get("topology"),
            "gpus": caps.get("gpus"),
        },
    }

    if coordinator_rtt_ms is not None:
        payload["coordinator_rtt_ms"] = coordinator_rtt_ms
        payload["path"] = {
            "path_type": PATH_TYPE_DIRECT,
            "path_class": infer_path_class_from_rtt(coordinator_rtt_ms),
            "coordinator_rtt_ms": coordinator_rtt_ms,
            "measurement_kind": MEASUREMENT_MEASURED,
        }

    return payload


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
    global _last_coordinator_rtt_ms

    payload = build_heartbeat_payload(
        config,
        gpu_status=gpu_status,
        is_online=is_online,
        coordinator_rtt_ms=_last_coordinator_rtt_ms,
    )

    if dry_run:
        logger.info("Dry-run heartbeat to %s", heartbeat_url(config))
        logger.info("Payload:\n%s", redact_payload_for_log(payload))
        return None

    started = time.perf_counter()
    try:
        response = _post_heartbeat(config, payload)
    except httpx.HTTPError as exc:
        logger.error("Heartbeat failed: %s", exc)
        raise

    _last_coordinator_rtt_ms = (time.perf_counter() - started) * 1000.0

    if response.status_code >= 400:
        detail = response.text
        logger.error("Heartbeat rejected (%s): %s", response.status_code, detail)
        response.raise_for_status()

    logger.info("Heartbeat accepted for peer %s (status %s)", config.peer_id, response.status_code)
    return cast(dict[str, Any], response.json())
