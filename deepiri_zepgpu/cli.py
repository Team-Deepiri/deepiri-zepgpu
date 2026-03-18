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


if __name__ == "__main__":
    main()
