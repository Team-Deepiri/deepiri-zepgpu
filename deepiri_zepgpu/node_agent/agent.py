"""CLI entry point for the room node agent."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Any

import click

from deepiri_zepgpu.node_agent.config import NodeAgentConfig, build_config
from deepiri_zepgpu.node_agent.heartbeat import send_heartbeat
from deepiri_zepgpu.node_agent.task_client import NodeTaskClient
from deepiri_zepgpu.node_agent.task_worker import NodeTaskWorker

logger = logging.getLogger(__name__)
_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    logger.info("Received signal %s, shutting down...", signum)
    _shutdown = True


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _cli_overrides(
    api_base_url: str | None,
    room_id: str | None,
    peer_id: str | None,
    auth_token: str | None,
    heartbeat_interval_seconds: int | None,
    task_poll_interval_seconds: int | None,
    endpoint: str | None,
    simulate: bool,
    enable_task_worker: bool,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if api_base_url is not None:
        overrides["api_base_url"] = api_base_url
    if room_id is not None:
        overrides["room_id"] = room_id
    if peer_id is not None:
        overrides["peer_id"] = peer_id
    if auth_token is not None:
        overrides["auth_token"] = auth_token
    if heartbeat_interval_seconds is not None:
        overrides["heartbeat_interval_seconds"] = heartbeat_interval_seconds
    if task_poll_interval_seconds is not None:
        overrides["task_poll_interval_seconds"] = task_poll_interval_seconds
    if endpoint is not None:
        overrides["endpoint"] = endpoint
    if simulate:
        overrides["simulation_mode"] = True
    if enable_task_worker:
        overrides["enable_task_worker"] = True
    return overrides


def build_task_worker(config: NodeAgentConfig) -> NodeTaskWorker:
    """Build the Phase 5 node task polling worker."""
    client = NodeTaskClient(
        base_url=config.api_base_url,
        room_id=config.room_id,
        peer_id=config.peer_id,
        token=config.auth_token,
    )
    return NodeTaskWorker(
        client=client,
        poll_interval_seconds=config.task_poll_interval_seconds,
    )


async def _run_task_worker_once_async(config: NodeAgentConfig) -> int:
    """Run one async task polling iteration and close the HTTP client."""
    worker = build_task_worker(config)
    try:
        return await worker.run_once()
    finally:
        await worker.client.close()


def run_task_worker_once(config: NodeAgentConfig) -> int:
    """Run one task polling iteration from the sync node-agent loop."""
    return asyncio.run(_run_task_worker_once_async(config))


def run_agent(config: NodeAgentConfig, *, once: bool = False, dry_run: bool = False) -> None:
    global _shutdown
    _shutdown = False

    if not once and not dry_run:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    while True:
        send_heartbeat(config, dry_run=dry_run)

        if config.enable_task_worker and not dry_run:
            processed = run_task_worker_once(config)
            if processed:
                logger.info("Processed %s node task assignment(s)", processed)

        if once or dry_run or _shutdown:
            break

        time.sleep(config.heartbeat_interval_seconds)


@click.command()
@click.option(
    "--config", "config_path", type=click.Path(exists=True, dir_okay=False), help="JSON config file"
)
@click.option("--api-base-url", default=None, help="Relay API base URL")
@click.option("--room-id", default=None, help="Room UUID")
@click.option("--peer-id", default=None, help="Peer UUID")
@click.option("--auth-token", default=None, help="Bearer auth token")
@click.option("--heartbeat-interval-seconds", default=None, type=int, help="Heartbeat interval")
@click.option("--task-poll-interval-seconds", default=None, type=int, help="Task poll interval")
@click.option("--endpoint", default=None, help="Optional peer endpoint URL")
@click.option("--once", is_flag=True, help="Send one heartbeat and exit")
@click.option("--simulate", is_flag=True, help="Use simulated GPU metrics")
@click.option("--enable-task-worker", is_flag=True, help="Enable Phase 5 task polling worker")
@click.option("--dry-run", is_flag=True, help="Print heartbeat payload without sending")
@click.option("--verbose", is_flag=True, help="Debug logging")
def main(
    config_path: str | None,
    api_base_url: str | None,
    room_id: str | None,
    peer_id: str | None,
    auth_token: str | None,
    heartbeat_interval_seconds: int | None,
    task_poll_interval_seconds: int | None,
    endpoint: str | None,
    once: bool,
    simulate: bool,
    enable_task_worker: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Run the ZepGPU room node agent heartbeat loop."""
    _configure_logging(verbose)

    if config_path is None and not all([api_base_url, room_id, peer_id, auth_token]):
        raise click.UsageError(
            "Provide --config or all of --api-base-url, --room-id, --peer-id, --auth-token"
        )

    try:
        config = build_config(
            config_path=config_path,
            overrides=_cli_overrides(
                api_base_url,
                room_id,
                peer_id,
                auth_token,
                heartbeat_interval_seconds,
                task_poll_interval_seconds,
                endpoint,
                simulate,
                enable_task_worker,
            ),
        )
    except Exception as exc:
        logger.error("Invalid configuration: %s", exc)
        raise SystemExit(1) from exc

    logger.info("Starting node agent for room %s peer %s", config.room_id, config.peer_id)
    logger.debug("Config: %s", config)

    try:
        run_agent(config, once=once or dry_run, dry_run=dry_run)
    except Exception as exc:
        logger.error("Node agent failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
