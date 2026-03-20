#!/usr/bin/env python3
"""CLI entry point for deepiri-zepgpu."""

import asyncio
import sys
from typing import Optional

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
        print("Click not installed. Running basic CLI...")
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
        sys.exit(1)

    command = sys.argv[1]

    if command == "serve":
        print("Starting server...")
        from deepiri_zepgpu.cli import serve
        asyncio.run(serve())
    elif command == "gpu":
        from deepiri_zepgpu.utils.gpu_utils import get_gpu_info
        import json
        info = get_gpu_info()
        print(json.dumps(info, indent=2))
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
        from deepiri_zepgpu.utils.gpu_utils import get_gpu_info
        import json
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
        from deepiri_zepgpu.queue.tasks import execute_gang_task
        import uuid
        gang_id = str(uuid.uuid4())
        result = execute_gang_task.delay(gang_id)
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


if __name__ == "__main__":
    main()
