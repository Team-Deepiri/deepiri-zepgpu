#!/usr/bin/env python3
"""CLI entry point for deepiri-zepgpu."""

import asyncio
import sys

try:
    import click
    HAS_CLICK = True
except ImportError:
    HAS_CLICK = False


def main():
    """Main CLI entry point."""
    if HAS_CLICK:
        cli()
    else:
        basic_cli()


def basic_cli():
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
    def cli():
        """DeepIRI ZepGPU - Serverless GPU Framework."""
        pass

    @cli.command()
    @click.option("--host", default="0.0.0.0", help="Host to bind to")
    @click.option("--port", default=8000, help="Port to bind to")
    def serve(host, port):
        """Start the API server."""
        from deepiri_zepgpu.cli import serve as serve_func
        asyncio.run(serve_func(host, port))

    @cli.command()
    @click.argument("function")
    @click.option("--gpu-memory", default=1024, help="GPU memory in MB")
    @click.option("--timeout", default=3600, help="Timeout in seconds")
    def submit(function, gpu_memory, timeout):
        """Submit a GPU task."""
        print(f"Submitting task: {function}")

    @cli.command()
    @click.option("--user", help="Filter by user ID")
    @click.option("--status", help="Filter by status")
    def list(user, status):
        """List tasks."""
        print("Listing tasks...")

    @cli.command()
    @click.argument("task_id")
    def status(task_id):
        """Show task status."""
        print(f"Status for task: {task_id}")

    @cli.command()
    @click.argument("task_id")
    def cancel(task_id):
        """Cancel a task."""
        print(f"Cancelling task: {task_id}")

    @cli.command()
    def gpu():
        """Show GPU information."""
        import json

        from deepiri_zepgpu.utils.gpu_utils import get_gpu_info
        info = get_gpu_info()
        print(json.dumps(info, indent=2))

    @cli.command()
    def db_upgrade():
        """Run database migrations (upgrade)."""
        import subprocess
        subprocess.run(["alembic", "upgrade", "head"])

    @cli.command()
    def db_downgrade():
        """Run database migrations (downgrade)."""
        import subprocess
        subprocess.run(["alembic", "downgrade", "-1"])

    @cli.command()
    def db_create():
        """Create database tables."""
        import subprocess
        subprocess.run(["alembic", "upgrade", "head"])

    @cli.command()
    def db_history():
        """Show migration history."""
        import subprocess
        subprocess.run(["alembic", "history", "--verbose"])

    @cli.command()
    def beat_sync():
        """Sync schedules to Celery Beat."""
        from deepiri_zepgpu.queue.beat_sync import beat_scheduler_sync
        synced = beat_scheduler_sync.sync_all_schedules()
        print(f"Synced {synced} schedules to Celery Beat")

    @cli.command()
    @click.option("--schedule-id", required=True, help="Schedule ID to trigger")
    def beat_trigger(schedule_id):
        """Trigger a scheduled task to run immediately."""
        from deepiri_zepgpu.queue.tasks import execute_scheduled_task
        result = execute_scheduled_task.delay(schedule_id)
        print(f"Triggered schedule {schedule_id}, task ID: {result.id}")

    @cli.command()
    def beat_status():
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
    def celery_worker():
        """Start a Celery worker."""
        import subprocess
        import sys
        sys.exit(subprocess.call([
            "celery", "-A", "deepiri_zepgpu.queue.celery_app",
            "worker", "--loglevel=info", "--queues=gpu_tasks,schedules"
        ]))

    @cli.command()
    def celery_beat():
        """Start Celery Beat scheduler."""
        import subprocess
        import sys
        sys.exit(subprocess.call([
            "celery", "-A", "deepiri_zepgpu.queue.celery_app",
            "beat", "--loglevel=info"
        ]))

    @cli.command()
    @click.option("--num-gpus", default=2, help="Number of GPUs required")
    @click.option("--name", required=True, help="Gang task name")
    @click.option("--priority", default=2, help="Task priority (1-5)")
    def gang_create(num_gpus, name, priority):
        """Create a new gang scheduled task."""
        import uuid

        from deepiri_zepgpu.queue.tasks import execute_gang_task
        gang_id = str(uuid.uuid4())
        execute_gang_task.delay(gang_id)
        print(f"Created gang task {gang_id} with name '{name}', {num_gpus} GPUs")

    @cli.command()
    def gang_list():
        """List pending gang tasks."""
        print("Listing gang tasks...")

    @cli.command()
    def preempt_check():
        """Trigger preemption check manually."""
        from deepiri_zepgpu.queue.tasks import check_and_preempt
        result = check_and_preempt.delay()
        print(f"Preemption check triggered, task ID: {result.id}")

    @cli.command()
    def fair_share_status():
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
    def vpn():
        """ZepGPU VPN - GPU sharing network management."""
        pass

    @vpn.command()
    @click.option("--config", type=click.Path(exists=True), help="Path to WireGuard .conf file")
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    def vpn_join(config, relay_url, interface):
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
    def vpn_leave(interface):
        """Leave the current VPN network."""
        if remove_wireguard_config(interface):
            click.echo(f"Disconnected from VPN ({interface})")
        else:
            click.echo("Failed to disconnect from VPN", err=True)

    @vpn.command()
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    def vpn_status(interface):
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
    @click.option("--api-token", envvar="ZEPGPU_API_TOKEN", default=None, help="Bearer token for relay")
    def gpu_pool(relay_url, api_token):
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
                click.echo(f"  [{gpu['username']}] {gpu['name']} - {gpu['total_memory_mb'] // 1024}GB - {gpu['state']}")
        except Exception as e:
            click.echo(f"Failed to fetch GPU pool: {e}", err=True)

    @vpn.command()
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    @click.option("--peer-id", envvar="ZEPGPU_PEER_ID", default=None, help="Peer UUID from join")
    def advertise(relay_url, interface, peer_id):
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
            click.echo("Set --peer-id or ZEPGPU_PEER_ID, or join with --code to save peer id.", err=True)
            return
        click.echo(f"Advertising GPUs to {relay_url}... (Ctrl+C to stop)")

        async def advertise_loop():
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

    from pathlib import Path


if __name__ == "__main__":
    main()
