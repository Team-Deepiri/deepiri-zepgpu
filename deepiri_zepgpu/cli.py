#!/usr/bin/env python3
"""CLI entry point for deepiri-zepgpu."""

import asyncio
import sys

try:
    import click

    HAS_CLICK = True
except ImportError:
    HAS_CLICK = False


def main() -> None:
    """Main CLI entry point."""
    if HAS_CLICK:
        cli()
    else:
        basic_cli()


def basic_cli() -> None:
    """Basic CLI without click."""
    if len(sys.argv) < 2:
        print("Usage: deepiri-gpu <command> [options]")
        print("\nCommands:")
        print("  serve     Start the API server")
        print("  submit    Submit a task")
        print("  list      List tasks")
        print("  status    Show task status")
        print("  cancel    Cancel a task")
        print("  gpu       Show GPU info")
        print("  vpn       VPN network management")
        sys.exit(1)

    command = sys.argv[1]

    if command == "serve":
        print("Starting server...")
        from deepiri_zepgpu.cli import serve

        asyncio.run(serve())
    elif command == "gpu":
        import json

        from deepiri_zepgpu.utils.gpu_utils import get_gpu_info

        info = get_gpu_info()
        print(json.dumps(info, indent=2))
    elif command == "vpn":
        if len(sys.argv) < 3:
            print("Usage: deepiri-gpu vpn <subcommand>")
            print("  join     Join a VPN network")
            print("  leave    Leave VPN network")
            print("  status   Show VPN status")
            print("  advertise  Advertise GPUs")
            print("  list-gpus  List network GPUs")
            sys.exit(1)
        subcommand = sys.argv[2]
        if subcommand == "status":
            from deepiri_zepgpu.vpn.cli import vpn as vpn_group

            vpn_group()
        else:
            print(f"Unknown vpn subcommand: {subcommand}")
            sys.exit(1)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if HAS_CLICK:

    @click.group()
    def cli() -> None:
        """DeepIRI ZepGPU - Serverless GPU Framework."""
        pass

    @cli.command()
    @click.option("--host", default="0.0.0.0", help="Host to bind to")
    @click.option("--port", default=8000, help="Port to bind to")
    def serve(host: str, port: int) -> None:
        """Start the API server."""
        from deepiri_zepgpu.cli import serve as serve_func

        asyncio.run(serve_func(host, port))

    @cli.command()
    @click.argument("function")
    @click.option("--gpu-memory", default=1024, help="GPU memory in MB")
    @click.option("--timeout", default=3600, help="Timeout in seconds")
    def submit(function: str, gpu_memory: int, timeout: int) -> None:
        """Submit a GPU task."""
        print(f"Submitting task: {function}")

    @cli.command()
    @click.option("--user", help="Filter by user ID")
    @click.option("--status", help="Filter by status")
    def list(user: str | None, status: str | None) -> None:
        """List tasks."""
        print("Listing tasks...")

    @cli.command()
    @click.argument("task_id")
    def status(task_id: str) -> None:
        """Show task status."""
        print(f"Status for task: {task_id}")

    @cli.command()
    @click.argument("task_id")
    def cancel(task_id: str) -> None:
        """Cancel a task."""
        print(f"Cancelling task: {task_id}")

    @cli.command()
    def gpu() -> None:
        """Show GPU information."""
        import json

        from deepiri_zepgpu.utils.gpu_utils import get_gpu_info

        info = get_gpu_info()
        print(json.dumps(info, indent=2))

    @cli.command()
    def db_upgrade() -> None:
        """Run database migrations (upgrade)."""
        import subprocess

        subprocess.run(["alembic", "upgrade", "head"])

    @cli.command()
    def db_downgrade() -> None:
        """Run database migrations (downgrade)."""
        import subprocess

        subprocess.run(["alembic", "downgrade", "-1"])

    @cli.command()
    def db_create() -> None:
        """Create database tables."""
        import subprocess

        subprocess.run(["alembic", "upgrade", "head"])

    @cli.command()
    def db_history() -> None:
        """Show migration history."""
        import subprocess

        subprocess.run(["alembic", "history", "--verbose"])

    @cli.command()
    def beat_sync() -> None:
        """Sync schedules to Celery Beat."""
        from deepiri_zepgpu.queue.beat_sync import beat_scheduler_sync

        synced = beat_scheduler_sync.sync_all_schedules()
        print(f"Synced {synced} schedules to Celery Beat")

    @cli.command()
    @click.option("--schedule-id", required=True, help="Schedule ID to trigger")
    def beat_trigger(schedule_id: str) -> None:
        """Trigger a scheduled task to run immediately."""
        from deepiri_zepgpu.queue.tasks import execute_scheduled_task

        result = execute_scheduled_task.delay(schedule_id)
        print(f"Triggered schedule {schedule_id}, task ID: {result.id}")

    @cli.command()
    def beat_status() -> None:
        """Show Celery Beat schedule status."""
        from deepiri_zepgpu.queue.beat_sync import beat_scheduler_sync

        schedules = beat_scheduler_sync.get_beat_schedule()
        if schedules:
            print(f"Active schedules in beat: {len(schedules)}")
            for schedule_id, entry in schedules.items():
                print(f"  - {schedule_id}: {entry.get('task', 'N/A')}")
        else:
            print("No active schedules in beat")

    @cli.command()
    def celery_worker() -> None:
        """Start a Celery worker."""
        import subprocess
        import sys

        sys.exit(
            subprocess.call(
                [
                    "celery",
                    "-A",
                    "deepiri_zepgpu.queue.celery_app",
                    "worker",
                    "--loglevel=info",
                    "--queues=gpu_tasks,schedules",
                ]
            )
        )

    @cli.command()
    def celery_beat() -> None:
        """Start Celery Beat scheduler."""
        import subprocess
        import sys

        sys.exit(
            subprocess.call(
                ["celery", "-A", "deepiri_zepgpu.queue.celery_app", "beat", "--loglevel=info"]
            )
        )

    @cli.command()
    @click.option("--num-gpus", default=2, help="Number of GPUs required")
    @click.option("--name", required=True, help="Gang task name")
    @click.option("--priority", default=2, help="Task priority (1-5)")
    def gang_create(num_gpus: int, name: str, priority: int) -> None:
        """Create a new gang scheduled task."""
        import uuid

        from deepiri_zepgpu.queue.tasks import execute_gang_task

        gang_id = str(uuid.uuid4())
        execute_gang_task.delay(gang_id)
        print(f"Created gang task {gang_id} with name '{name}', {num_gpus} GPUs")

    @cli.command()
    def gang_list() -> None:
        """List pending gang tasks."""
        print("Listing gang tasks...")

    @cli.command()
    def preempt_check() -> None:
        """Trigger preemption check manually."""
        from deepiri_zepgpu.queue.tasks import check_and_preempt

        result = check_and_preempt.delay()
        print(f"Preemption check triggered, task ID: {result.id}")

    @cli.command()
    def fair_share_status() -> None:
        """Show fair share scheduling status."""
        from deepiri_zepgpu.queue.tasks import get_fair_share_weights

        result = get_fair_share_weights.delay()
        weights = result.get(timeout=10)
        print("Fair Share Weights:")
        for user_id, data in weights.get("weights", {}).items():
            print(f"  {user_id}: weight={data['weight']:.2f}, used={data['gpu_seconds_used']:.0f}s")

    from deepiri_zepgpu.vpn.cli import (
        apply_wireguard_config,
        check_wireguard_installed,
        get_config_dir,
        get_vpn_ip,
        install_wireguard,
        remove_wireguard_config,
        vpn_settings,
    )

    @cli.group()
    def vpn() -> None:
        """ZepGPU VPN - GPU sharing network management."""
        pass

    @vpn.command()
    @click.option("--config", type=click.Path(exists=True), help="Path to WireGuard .conf file")
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    def vpn_join(config: str | None, relay_url: str, interface: str) -> None:
        """Join a VPN network."""
        if not check_wireguard_installed():
            print("WireGuard is not installed.")
            install_wireguard()
            return
        if not config:
            click.echo("Please provide a WireGuard config file with --config")
            return
        config_text = Path(config).read_text()
        if apply_wireguard_config(config_text, interface):
            vpn_ip = get_vpn_ip()
            click.echo(f"Connected to VPN! Your IP: {vpn_ip}")
        else:
            click.echo("Failed to apply WireGuard config", err=True)

    @vpn.command()
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    def vpn_leave(interface: str) -> None:
        """Leave the current VPN network."""
        if remove_wireguard_config(interface):
            click.echo(f"Disconnected from VPN ({interface})")
        else:
            click.echo("Failed to disconnect from VPN", err=True)

    @vpn.command()
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    def vpn_status(interface: str) -> None:
        """Show VPN connection status."""
        import subprocess

        result = subprocess.run(["wg", "show", interface], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            click.echo(f"WireGuard interface [{interface}]:")
            click.echo(result.stdout)
            vpn_ip = get_vpn_ip()
            if vpn_ip:
                click.echo(f"VPN IP: {vpn_ip}")
        else:
            click.echo(f"Not connected to VPN ({interface} is down or not configured)")
        click.echo(f"\nConfig directory: {get_config_dir()}")

    @vpn.command()
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option(
        "--api-token", envvar="ZEPGPU_API_TOKEN", default=None, help="Bearer token for relay"
    )
    def gpu_pool(relay_url: str, api_token: str | None) -> None:
        """List GPUs available in the network pool."""
        import httpx

        from deepiri_zepgpu.vpn.cli import vpn_api_url

        if not api_token:
            click.echo("gpu-pool requires --api-token or ZEPGPU_API_TOKEN", err=True)
            return
        try:
            response = httpx.get(
                vpn_api_url(relay_url, "/gpu-pool"),
                headers={"Authorization": f"Bearer {api_token}"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            click.echo("GPU Pool:")
            click.echo(f"  Total GPUs: {data['total_gpus']}")
            click.echo(f"  Total Memory: {data['total_memory_mb'] // 1024}GB")
            click.echo(f"  Available Memory: {data['available_memory_mb'] // 1024}GB")
            click.echo(f"  Online Peers: {data['online_peers']}")
            for gpu in data.get("gpu_breakdown", []):
                click.echo(
                    f"  [{gpu['username']}] {gpu['name']} - {gpu['total_memory_mb'] // 1024}GB - {gpu['state']}"
                )
        except Exception as e:
            click.echo(f"Failed to fetch GPU pool: {e}", err=True)

    @vpn.command()
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    @click.option("--peer-id", envvar="ZEPGPU_PEER_ID", default=None, help="Peer UUID from join")
    def advertise(relay_url: str, interface: str, peer_id: str | None) -> None:
        """Advertise local GPUs to the relay server."""
        from deepiri_zepgpu.vpn.cli import (
            get_vpn_ip,
            install_wireguard,
            load_peer_id,
            vpn_api_url,
        )

        if not check_wireguard_installed():
            click.echo("WireGuard is not installed.")
            install_wireguard()
            return
        vpn_ip = get_vpn_ip()
        if not vpn_ip:
            click.echo("Not connected to VPN. Run 'deepiri-gpu vpn vpn-join' first.", err=True)
            return
        resolved = peer_id or load_peer_id()
        if not resolved:
            click.echo(
                "Set --peer-id or ZEPGPU_PEER_ID, or join with --code to save peer id.", err=True
            )
            return
        click.echo(f"Advertising GPUs to {relay_url}... (Ctrl+C to stop)")

        async def advertise_loop() -> None:
            import httpx

            from deepiri_zepgpu.vpn.peer_node import discover_local_gpus

            while True:
                gpus = discover_local_gpus()
                if gpus:
                    for g in gpus:
                        click.echo(f"  {g.name} - {g.total_memory_mb // 1024}GB")
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(
                            vpn_api_url(relay_url, "/peers/heartbeat"),
                            json={
                                "peer_id": resolved,
                                "gpu_status": [g.model_dump() for g in gpus],
                                "is_online": True,
                            },
                        )
                        click.echo("  GPU status advertised")
                except Exception as e:
                    click.echo(f"  Failed: {e}")
                await asyncio.sleep(vpn_settings.heartbeat_interval_seconds)

        try:
            asyncio.run(advertise_loop())
        except KeyboardInterrupt:
            click.echo("\nStopped.")

    @cli.group()
    def ledger() -> None:
        """Permissioned compute ledger (status, verify, sync)."""
        pass

    @ledger.command("status")
    @click.option("--network-id", default=None, help="VPN network UUID for scoped chain")
    def ledger_status_cmd(network_id: str | None) -> None:
        """Show ledger tip / quorum status."""
        from deepiri_zepgpu.compute_ledger.cli_ops import dump_json, ledger_status

        dump_json(asyncio.run(ledger_status(network_id)))

    @ledger.command("verify")
    @click.option("--network-id", default=None, help="VPN network UUID for scoped chain")
    def ledger_verify_cmd(network_id: str | None) -> None:
        """Verify hash linkage, PoA signatures, and credit replay."""
        from deepiri_zepgpu.compute_ledger.cli_ops import dump_json, ledger_verify

        result = asyncio.run(ledger_verify(network_id))
        dump_json(result)
        raise SystemExit(0 if result.get("valid") else 1)

    @ledger.command("sync-headers")
    @click.option("--network-id", default=None, help="VPN network UUID for scoped chain")
    @click.option("--from-height", default=0, type=int, help="Start height")
    @click.option("--limit", default=100, type=int, help="Max headers")
    def ledger_sync_headers_cmd(network_id: str | None, from_height: int, limit: int) -> None:
        """Export compact headers for light-client sync."""
        from deepiri_zepgpu.compute_ledger.cli_ops import dump_json, ledger_sync_headers

        dump_json(asyncio.run(ledger_sync_headers(network_id, from_height, limit)))

    @ledger.command("revolution-audit")
    @click.option("--offline", is_flag=True, help="Skip DB scenarios (golden + crypto only)")
    @click.option("--json-out", type=click.Path(), default=None, help="Write JSON report path")
    @click.option("--md-out", type=click.Path(), default=None, help="Write Markdown report path")
    def ledger_revolution_audit_cmd(
        offline: bool, json_out: str | None, md_out: str | None
    ) -> None:
        """Run revolutionary verification: golden vectors, adversary suite, credit economy."""
        from pathlib import Path

        from deepiri_zepgpu.compute_ledger.revolution import run_revolution_audit
        from deepiri_zepgpu.compute_ledger.revolution.audit import RevolutionAuditResult
        from deepiri_zepgpu.compute_ledger.revolution.report import (
            render_console_summary,
            write_audit_json,
            write_audit_markdown,
        )
        from deepiri_zepgpu.database.session import get_db_context

        async def _run() -> RevolutionAuditResult:
            if offline:
                return await run_revolution_audit(None, include_db=False)
            async with get_db_context() as db:
                return await run_revolution_audit(db, include_db=True)

        typed = asyncio.run(_run())
        if json_out:
            write_audit_json(typed, Path(json_out))
            click.echo(f"Wrote {json_out}")
        if md_out:
            write_audit_markdown(typed, Path(md_out))
            click.echo(f"Wrote {md_out}")
        click.echo(render_console_summary(typed))
        if not json_out and not md_out:
            from deepiri_zepgpu.compute_ledger.cli_ops import dump_json

            dump_json(typed.to_dict())
        raise SystemExit(0 if typed.passed else 1)

    from pathlib import Path


if __name__ == "__main__":
    main()
