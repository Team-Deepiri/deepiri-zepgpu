"""CLI entry point for the room node agent."""

from __future__ import annotations

import asyncio
import logging
import signal
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
    task_poll_limit: int | None,
    endpoint: str | None,
    simulate: bool,
    enable_task_worker: bool,
) -> dict[str, Any]:
    """Build the config override dict from CLI flags.

    Optional value-bearing flags (None means "not passed") are collapsed
    into a single filter instead of one `if ... is not None` branch per
    flag, to keep this from growing a branch every time a new CLI option
    is added. The two boolean flags stay as explicit checks since `False`
    is a valid "don't set" value for them, not an override.
    """
    optional_values: dict[str, Any] = {
        "api_base_url": api_base_url,
        "room_id": room_id,
        "peer_id": peer_id,
        "auth_token": auth_token,
        "heartbeat_interval_seconds": heartbeat_interval_seconds,
        "task_poll_interval_seconds": task_poll_interval_seconds,
        "task_poll_limit": task_poll_limit,
        "endpoint": endpoint,
    }
    overrides: dict[str, Any] = {
        key: value for key, value in optional_values.items() if value is not None
    }
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
        poll_limit=config.task_poll_limit,
    )


async def _run_task_worker_once_async(config: NodeAgentConfig) -> int:
    """Run one async task polling iteration and close the HTTP client."""
    worker = build_task_worker(config)
    try:
        return await worker.run_once()
    finally:
        await worker.client.close()


def run_task_worker_once(config: NodeAgentConfig) -> int:
    """Run one task polling iteration from the sync node-agent loop.

    Used by the single-pass (`--once` / `--dry-run`) path only. The
    continuous loop below (`_run_agent_forever_async`) does NOT call this
    -- it reuses one event loop for the process lifetime instead of
    spinning one up via asyncio.run() on every heartbeat tick.
    """
    return asyncio.run(_run_task_worker_once_async(config))


async def _run_agent_forever_async(config: NodeAgentConfig) -> None:
    """Continuous heartbeat + task-poll loop under a single event loop.

    Builds the task worker (and its HTTP client) once and reuses it for
    the life of the process, instead of the previous pattern of calling
    asyncio.run() -- which creates and tears down a whole new event loop
    -- on every heartbeat tick.
    """
    worker = build_task_worker(config) if config.enable_task_worker else None
    try:
        while True:
            await asyncio.to_thread(send_heartbeat, config, dry_run=False)

            if worker is not None:
                processed = await worker.run_once()
                if processed:
                    logger.info("Processed %s node task assignment(s)", processed)

            if _shutdown:
                break

            await asyncio.sleep(config.heartbeat_interval_seconds)
    finally:
        if worker is not None:
            await worker.client.close()


def run_agent(config: NodeAgentConfig, *, once: bool = False, dry_run: bool = False) -> None:
    global _shutdown
    _shutdown = False

    if once or dry_run:
        # Single pass: exactly the original synchronous behavior. Kept
        # separate from the continuous loop so `--once`/`--dry-run`
        # invocations don't need a long-lived event loop, and so the
        # existing agent tests (which patch run_task_worker_once and only
        # ever call run_agent with once=True) keep passing unchanged.
        send_heartbeat(config, dry_run=dry_run)
        if config.enable_task_worker and not dry_run:
            processed = run_task_worker_once(config)
            if processed:
                logger.info("Processed %s node task assignment(s)", processed)
        return

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    asyncio.run(_run_agent_forever_async(config))


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
@click.option(
    "--task-poll-limit",
    default=None,
    type=int,
    help="Max assignments to pull per poll (1-10)",
)
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
    task_poll_limit: int | None,
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
                task_poll_limit,
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
