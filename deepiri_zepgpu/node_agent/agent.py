"""CLI for provider join, serve, status, and credential reset."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from typing import Any

import click
import httpx

from deepiri_zepgpu.node_agent.config import (
    AGENT_VERSION,
    NodeAgentConfig,
    build_config,
    clear_agent_identity,
    default_agent_path,
    identity_status_dict,
    load_agent_identity,
    save_agent_identity,
    validate_coordinator_url,
)
from deepiri_zepgpu.node_agent.heartbeat import send_heartbeat
from deepiri_zepgpu.node_agent.provider_ws import ProviderAssignmentSocket
from deepiri_zepgpu.node_agent.task_client import NodeTaskClient
from deepiri_zepgpu.node_agent.task_worker import NodeTaskWorker
from deepiri_zepgpu.node_agent.training_runner import TrainingAgentRunner

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
    node_name: str | None = None,
    provider_mode: str | None = None,
) -> dict[str, Any]:
    optional_values: dict[str, Any] = {
        "api_base_url": api_base_url,
        "room_id": room_id,
        "peer_id": peer_id,
        "auth_token": auth_token,
        "heartbeat_interval_seconds": heartbeat_interval_seconds,
        "task_poll_interval_seconds": task_poll_interval_seconds,
        "task_poll_limit": task_poll_limit,
        "endpoint": endpoint,
        "node_name": node_name,
        "provider_mode": provider_mode,
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
    worker = build_task_worker(config)
    try:
        await worker.reconcile_on_startup()
        return await worker.run_once()
    finally:
        await worker.client.close()


def run_task_worker_once(config: NodeAgentConfig) -> int:
    return asyncio.run(_run_task_worker_once_async(config))


async def _run_agent_forever_async(config: NodeAgentConfig) -> None:  # noqa: C901
    worker = build_task_worker(config) if config.enable_task_worker else None
    training_runner = TrainingAgentRunner(provider_token=config.auth_token)
    provider_ws: ProviderAssignmentSocket | None = None
    try:
        if worker is not None:
            await worker.reconcile_on_startup()

        async def _provider_message(message: dict[str, Any]) -> None:
            if await training_runner.handle_message(message):
                return
            if worker is not None:
                await worker.handle_provider_message(message)

        # Phase 18 launch/cancel is WSS-pushed even when the generic task
        # polling worker is disabled.
        provider_ws = ProviderAssignmentSocket(
            base_url=config.api_base_url,
            room_id=config.room_id,
            peer_id=config.peer_id,
            token=config.auth_token,
            on_message=_provider_message,
        )
        try:
            await provider_ws.start()
        except Exception:
            logger.warning(
                "Provider WSS unavailable; HTTPS heartbeats remain active",
                exc_info=True,
            )
            provider_ws = None

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
        if provider_ws is not None:
            await provider_ws.stop()
        await training_runner.close()
        if worker is not None:
            await worker.client.close()


def run_agent(config: NodeAgentConfig, *, once: bool = False, dry_run: bool = False) -> None:
    global _shutdown
    _shutdown = False

    if once or dry_run:
        send_heartbeat(config, dry_run=dry_run)
        if config.enable_task_worker and not dry_run:
            processed = run_task_worker_once(config)
            if processed:
                logger.info("Processed %s node task assignment(s)", processed)
        return

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    asyncio.run(_run_agent_forever_async(config))


def _login_human(
    client: httpx.Client,
    *,
    coordinator: str,
    username: str,
    password: str,
) -> str:
    response = client.post(
        f"{coordinator}/api/v1/users/login",
        json={"username": username, "password": password},
    )
    if response.status_code >= 400:
        detail = response.json().get("detail", response.text) if response.content else response.text
        raise click.ClickException(f"Login failed: {detail}")
    token = response.json().get("access_token")
    if not token:
        raise click.ClickException("Login response missing access_token")
    return str(token)


def join_room(
    *,
    invite: str,
    coordinator: str,
    username: str | None = None,
    password: str | None = None,
    human_token: str | None = None,
    node_name: str | None = None,
    provider_mode: str = "dialout",
    identity_path: str | None = None,
) -> NodeAgentConfig:
    """Authenticate as a human, redeem invite, persist provider identity."""

    coordinator = validate_coordinator_url(coordinator)
    with httpx.Client(timeout=30.0) as client:
        if human_token:
            access_token = human_token
        else:
            if not username or not password:
                raise click.UsageError(
                    "Provide --username/--password or --token for human authentication"
                )
            access_token = _login_human(
                client,
                coordinator=coordinator,
                username=username,
                password=password,
            )

        headers = {"Authorization": f"Bearer {access_token}"}
        join_body: dict[str, Any] = {
            "invite_code": invite,
            "provider_mode": provider_mode,
        }
        if node_name:
            join_body["node_name"] = node_name

        response = client.post(
            f"{coordinator}/api/v1/rooms/join",
            headers=headers,
            json=join_body,
        )
        if response.status_code >= 400:
            detail = (
                response.json().get("detail", response.text) if response.content else response.text
            )
            raise click.ClickException(f"Join failed ({response.status_code}): {detail}")

        payload = response.json()
        room = payload.get("room") or {}
        member = payload.get("member") or {}
        auth_token = payload.get("auth_token")
        if not auth_token:
            # Fallback for older coordinators: fetch from config endpoint.
            room_id = str(room.get("id"))
            config_resp = client.get(
                f"{coordinator}/api/v1/rooms/{room_id}/config",
                headers=headers,
            )
            config_resp.raise_for_status()
            auth_token = config_resp.json().get("auth_token")
        if not auth_token:
            raise click.ClickException("Join succeeded but no provider token was issued")

        expires = payload.get("token_expires_at")
        if isinstance(expires, str):
            token_expires_at = expires
        elif expires is not None:
            token_expires_at = str(expires)
        else:
            token_expires_at = None

        transport_mode = str(room.get("transport_mode") or provider_mode or "dialout").lower()
        vpn_ip: str | None = member.get("vpn_ip")
        vpn_ip = vpn_ip.strip() or None if isinstance(vpn_ip, str) else None
        wireguard_interface: str | None = None
        wireguard_mock = False

        if transport_mode == "wireguard":
            room_id = str(room["id"])
            peer_id = str(member["id"])
            config_resp = client.get(
                f"{coordinator}/api/v1/rooms/{room_id}/config",
                headers=headers,
            )
            if config_resp.status_code < 400:
                cfg_body = config_resp.json()
                config_text = cfg_body.get("config") or cfg_body.get("config_text")
                if not vpn_ip:
                    maybe_ip = cfg_body.get("vpn_ip")
                    vpn_ip = str(maybe_ip).strip() if maybe_ip else None
                if config_text:
                    from deepiri_zepgpu.vpn.cli import (
                        apply_wireguard_config,
                        check_wireguard_installed,
                        export_wireguard_config,
                        is_windows,
                        windows_import_instructions,
                    )
                    from deepiri_zepgpu.vpn.mock_tunnel import bring_up_mock_tunnel

                    if is_windows():
                        conf_path = export_wireguard_config(str(config_text), "wg0")
                        logger.warning("%s", windows_import_instructions(conf_path))
                        wireguard_interface = None
                        wireguard_mock = False
                    elif check_wireguard_installed():
                        if apply_wireguard_config(str(config_text), "wg0"):
                            wireguard_interface = "wg0"
                        else:
                            logger.warning(
                                "WireGuard tools present but apply failed; using mock tunnel"
                            )
                            mock = bring_up_mock_tunnel(
                                room_id=room_id,
                                peer_id=peer_id,
                                vpn_ip=vpn_ip,
                                config_text=str(config_text),
                            )
                            vpn_ip = mock.vpn_ip
                            wireguard_interface = mock.interface
                            wireguard_mock = True
                    else:
                        mock = bring_up_mock_tunnel(
                            room_id=room_id,
                            peer_id=peer_id,
                            vpn_ip=vpn_ip,
                            config_text=str(config_text),
                        )
                        vpn_ip = mock.vpn_ip
                        wireguard_interface = mock.interface
                        wireguard_mock = True
                        logger.info(
                            "WireGuard tools not installed; mock tunnel up at %s",
                            vpn_ip,
                        )

        config = NodeAgentConfig(
            api_base_url=coordinator,
            room_id=str(room["id"]),
            peer_id=str(member["id"]),
            auth_token=str(auth_token),
            heartbeat_interval_seconds=int(payload.get("heartbeat_interval_seconds") or 30),
            enable_task_worker=True,
            node_name=node_name,
            provider_mode=(
                transport_mode
                if transport_mode in {"dialout", "wireguard", "overlay"}
                else provider_mode
            ),
            agent_version=AGENT_VERSION,
            token_expires_at=token_expires_at,
            transport_mode=transport_mode,
            vpn_ip=vpn_ip,
            wireguard_interface=wireguard_interface,
            wireguard_mock=wireguard_mock,
        )
        path = save_agent_identity(config, path=identity_path)
        logger.info(
            "Joined room %s as provider %s; identity saved to %s",
            config.room_id,
            config.peer_id,
            path,
        )
        return config


@click.group()
@click.option("--verbose", is_flag=True, help="Debug logging")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """ZepGPU provider node agent (NAT-friendly dial-out)."""
    _configure_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@cli.command("join")
@click.option("--invite", required=True, help="Room invite code")
@click.option("--coordinator", required=True, help="Coordinator base URL (HTTPS)")
@click.option("--username", default=None, help="Human account username")
@click.option("--password", default=None, help="Human account password")
@click.option("--token", "human_token", default=None, help="Human JWT (alternative to password)")
@click.option("--node-name", default=None, help="Optional provider node display name")
@click.option("--provider-mode", default="dialout", show_default=True)
@click.option(
    "--identity",
    "identity_path",
    default=None,
    type=click.Path(dir_okay=False),
    help="Override ~/.zepgpu/agent.json path",
)
def join_cmd(
    invite: str,
    coordinator: str,
    username: str | None,
    password: str | None,
    human_token: str | None,
    node_name: str | None,
    provider_mode: str,
    identity_path: str | None,
) -> None:
    """Join a room with a human JWT, then persist the provider token locally."""
    try:
        config = join_room(
            invite=invite,
            coordinator=coordinator,
            username=username,
            password=password,
            human_token=human_token,
            node_name=node_name,
            provider_mode=provider_mode,
            identity_path=identity_path,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"Joined room {config.room_id} as provider {config.peer_id}. "
        f"Identity saved (token redacted). Run `zepgpu-node serve` next."
    )


@cli.command("serve")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="JSON config (defaults to ~/.zepgpu/agent.json)",
)
@click.option("--api-base-url", default=None, help="Relay API base URL")
@click.option("--room-id", default=None, help="Room UUID")
@click.option("--peer-id", default=None, help="Peer UUID")
@click.option("--auth-token", default=None, help="Bearer auth token")
@click.option("--heartbeat-interval-seconds", default=None, type=int)
@click.option("--task-poll-interval-seconds", default=None, type=int)
@click.option("--task-poll-limit", default=None, type=int)
@click.option("--endpoint", default=None)
@click.option("--once", is_flag=True, help="Send one heartbeat and exit")
@click.option("--simulate", is_flag=True, help="Use simulated GPU metrics")
@click.option("--enable-task-worker", is_flag=True, help="Enable task polling worker")
@click.option("--dry-run", is_flag=True, help="Print heartbeat payload without sending")
@click.option("--node-name", default=None)
@click.option("--provider-mode", default=None)
def serve_cmd(
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
    node_name: str | None,
    provider_mode: str | None,
) -> None:
    """Load identity and run heartbeat (+ optional task worker)."""
    resolved_path = config_path
    if resolved_path is None and not all([api_base_url, room_id, peer_id, auth_token]):
        resolved_path = str(default_agent_path())
        if not default_agent_path().exists():
            raise click.UsageError(
                "Provide --config / CLI credentials, or run `zepgpu-node join` first"
            )

    try:
        overrides = _cli_overrides(
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
            node_name=node_name,
            provider_mode=provider_mode,
        )
        # Default: enable task worker when serving from persisted identity.
        if resolved_path and not enable_task_worker and "enable_task_worker" not in overrides:
            overrides.setdefault("enable_task_worker", True)
        config = build_config(config_path=resolved_path, overrides=overrides)
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


@cli.command("status")
@click.option(
    "--identity",
    "identity_path",
    default=None,
    type=click.Path(dir_okay=False),
    help="Override ~/.zepgpu/agent.json path",
)
@click.option("--probe", is_flag=True, help="Probe coordinator health with provider token")
def status_cmd(identity_path: str | None, probe: bool) -> None:
    """Show redacted local identity and optional coordinator probe."""
    try:
        config = load_agent_identity(identity_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    probe_result: dict[str, Any] | None = None
    if probe:
        try:
            with httpx.Client(timeout=10.0) as client:
                health = client.get(f"{config.api_base_url}/api/v1/health")
                hb = client.post(
                    f"{config.api_base_url}/api/v1/rooms/{config.room_id}"
                    f"/nodes/{config.peer_id}/heartbeat",
                    headers={"Authorization": f"Bearer {config.auth_token}"},
                    json={
                        "is_online": True,
                        "agent_version": config.agent_version,
                        "node_name": config.node_name,
                        "provider_mode": config.provider_mode,
                        "gpu_status": [],
                    },
                )
                probe_result = {
                    "health_status": health.status_code,
                    "heartbeat_status": hb.status_code,
                    "checked_at": datetime.now().isoformat(),
                }
                if hb.status_code >= 400:
                    # Never echo response bodies that may contain tokens.
                    probe_result["heartbeat_ok"] = False
                else:
                    probe_result["heartbeat_ok"] = True
        except httpx.HTTPError as exc:
            probe_result = {"error": str(exc)}

    click.echo(identity_status_dict(config, probe=probe_result))


@cli.command("logout")
@click.option(
    "--identity",
    "identity_path",
    default=None,
    type=click.Path(dir_okay=False),
)
def logout_cmd(identity_path: str | None) -> None:
    """Clear local provider credentials and tear down WireGuard/mock tunnel if present."""
    try:
        config = load_agent_identity(identity_path)
    except FileNotFoundError:
        config = None
    if config is not None:
        if config.wireguard_mock:
            from deepiri_zepgpu.vpn.mock_tunnel import tear_down_mock_tunnel

            tear_down_mock_tunnel()
        elif config.wireguard_interface:
            from deepiri_zepgpu.vpn.cli import remove_wireguard_config

            remove_wireguard_config(config.wireguard_interface)
    removed = clear_agent_identity(identity_path)
    if removed:
        click.echo("Local provider credentials cleared.")
    else:
        click.echo("No local provider credentials found.")


@cli.command("reset")
@click.pass_context
def reset_cmd(ctx: click.Context) -> None:
    """Alias for logout."""
    ctx.invoke(logout_cmd)


# Backwards-compatible single-command entry used by older docs/tests.
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
    """Run the ZepGPU room node agent heartbeat loop (legacy entrypoint)."""
    _configure_logging(verbose)

    if config_path is None and not all([api_base_url, room_id, peer_id, auth_token]):
        # Prefer persisted identity when no explicit flags are given.
        if default_agent_path().exists():
            config_path = str(default_agent_path())
        else:
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
    cli()
