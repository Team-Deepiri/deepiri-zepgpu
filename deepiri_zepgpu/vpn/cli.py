"""CLI commands for VPN and GPU sharing."""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
from pathlib import Path

try:
    import click

    HAS_CLICK = True
except ImportError:
    HAS_CLICK = False

import contextlib

from deepiri_zepgpu.vpn.config import vpn_settings


def vpn_api_url(relay_url: str, path: str) -> str:
    p = path if path.startswith("/") else f"/{path}"
    return f"{relay_url.rstrip('/')}/api/v1/vpn{p}"


def get_config_dir() -> Path:
    path = vpn_settings.get_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def peer_state_path() -> Path:
    return get_config_dir() / "peer_state.json"


def save_peer_registration(peer_id: str, relay_url: str) -> None:
    import json

    path = peer_state_path()
    path.write_text(json.dumps({"peer_id": peer_id, "relay_url": relay_url}, indent=2))
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def load_peer_id() -> str | None:
    import json

    p = peer_state_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return data.get("peer_id")  # type: ignore[no-any-return]
    except Exception:
        return None


def get_wg_interface() -> str:
    return "wg0"


def is_linux() -> bool:
    return platform.system() == "Linux"


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_windows() -> bool:
    return platform.system() == "Windows"


def export_wireguard_config(config_text: str, interface: str = "wg0") -> Path:
    """Write a .conf for wg-quick or Windows WireGuard app import. Never silent-mock."""

    config_dir = get_config_dir()
    conf_path = config_dir / f"{interface}.conf"
    conf_path.write_text(config_text, encoding="utf-8")
    os.chmod(conf_path, 0o600)
    return conf_path


def windows_import_instructions(conf_path: Path) -> str:
    return (
        "WireGuard cannot be applied from the CLI on Windows. Import the config, then serve:\n"
        f"  1. Install WireGuard from https://www.wireguard.com/install/\n"
        f"  2. Open WireGuard → Add Tunnel → Import tunnel(s) from file\n"
        f"  3. Select: {conf_path}\n"
        "  4. Activate the tunnel, then run: zepgpu-node serve --enable-task-worker\n"
        "Logout does not remove a Windows app tunnel; deactivate it in WireGuard if needed."
    )


def apply_wireguard_config(config_text: str, interface: str = "wg0") -> bool:
    """Apply WireGuard config to the system."""
    conf_path = export_wireguard_config(config_text, interface=interface)

    if is_linux():
        result = subprocess.run(
            ["wg-quick", "up", str(conf_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"WireGuard up failed: {result.stderr}", file=sys.stderr)
            return False
        return True

    elif is_macos():
        result = subprocess.run(
            ["wg-quick", "up", str(conf_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["ln", "-sf", str(conf_path), f"/etc/wireguard/{interface}.conf"], check=True
            )
            result = subprocess.run(
                ["wg-quick", "up", f"/etc/wireguard/{interface}.conf"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"WireGuard up failed: {result.stderr}", file=sys.stderr)
                return False
        return True

    else:
        print(windows_import_instructions(conf_path), file=sys.stderr)
        return False


def remove_wireguard_config(interface: str = "wg0") -> bool:
    """Remove WireGuard config from the system."""
    if is_linux() or is_macos():
        config_dir = get_config_dir()
        conf_path = config_dir / f"{interface}.conf"
        result = subprocess.run(
            ["wg-quick", "down", str(conf_path)],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    return False


def get_vpn_ip() -> str | None:
    """Get the current VPN IP address."""
    if is_linux():
        result = subprocess.run(
            ["ip", "addr", "show", "wg0"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.split("\n"):
            if "inet " in line:
                parts = line.strip().split()
                return parts[1].split("/")[0]
    elif is_macos():
        result = subprocess.run(
            ["ifconfig", "utun*"],
            capture_output=True,
            text=True,
        )
    return None


def check_wireguard_installed() -> bool:
    """Check if WireGuard tools are installed."""
    try:
        result = subprocess.run(["wg", "--version"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def install_wireguard() -> bool:
    """Install WireGuard based on OS."""
    if is_linux():
        print("Please install WireGuard via your package manager:")
        print("  sudo apt install wireguard  # Debian/Ubuntu")
        print("  sudo dnf install wireguard-tools  # Fedora")
        print("  sudo pacman -S wireguard-tools  # Arch")
        return False
    elif is_macos():
        print("Please install WireGuard from the Mac App Store or via brew:")
        print("  brew install wireguard-tools")
        return False
    return False


if HAS_CLICK:

    @click.group()
    def vpn() -> None:
        """ZepGPU VPN - GPU sharing network management."""
        pass

    @vpn.command()
    @click.option("--config", type=click.Path(), help="Path to WireGuard config file (.conf)")
    @click.option("--code", help="Join code from relay server")
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    @click.option(
        "--api-token",
        envvar="ZEPGPU_API_TOKEN",
        default=None,
        help="Bearer token for relay API (required for --code)",
    )
    @click.option("--gpu-host", is_flag=True, help="Register as GPU host when using --code")
    def join(  # noqa: C901
        config: str | None,
        code: str | None,
        relay_url: str,
        interface: str,
        api_token: str | None,
        gpu_host: bool,
    ) -> None:
        """Join a VPN network."""
        if not check_wireguard_installed():
            print("WireGuard is not installed.")
            install_wireguard()
            sys.exit(1)

        if code:
            import httpx

            if not api_token:
                print("join --code requires --api-token or ZEPGPU_API_TOKEN", file=sys.stderr)
                sys.exit(1)
            try:
                r = httpx.post(
                    vpn_api_url(relay_url, "/join"),
                    json={"invite_code": code, "is_gpu_host": gpu_host},
                    headers={"Authorization": f"Bearer {api_token}"},
                    timeout=60,
                )
                r.raise_for_status()
                body = r.json()
                conf_text = body["config_text"]
                peer_id = body.get("peer_id")
                vpn_ip = body.get("vpn_ip")
                if apply_wireguard_config(conf_text, interface):
                    if peer_id:
                        save_peer_registration(peer_id, relay_url)
                    print(f"Connected to VPN! Your IP: {vpn_ip or get_vpn_ip()}")
                else:
                    print("Failed to apply WireGuard config", file=sys.stderr)
                    sys.exit(1)
            except httpx.HTTPStatusError as e:
                detail = ""
                try:
                    detail = e.response.json().get("detail", str(e))
                except Exception:
                    detail = str(e)
                print(f"Join failed: {detail}", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"Failed to connect to relay: {e}", file=sys.stderr)
                sys.exit(1)
            return

        if not config:
            print("Please provide a WireGuard config file with --config", file=sys.stderr)
            sys.exit(1)

        conf_path = Path(config)
        if not conf_path.exists():
            print(f"Config file not found: {config}", file=sys.stderr)
            sys.exit(1)

        config_text = conf_path.read_text()
        if apply_wireguard_config(config_text, interface):
            vpn_ip = get_vpn_ip()
            print(f"Connected to VPN! Your IP: {vpn_ip}")
        else:
            print("Failed to apply WireGuard config", file=sys.stderr)
            sys.exit(1)

    @vpn.command()
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    def leave(interface: str) -> None:
        """Leave the current VPN network."""
        if remove_wireguard_config(interface):
            print(f"Disconnected from VPN ({interface})")
        else:
            print("Failed to disconnect from VPN", file=sys.stderr)
            sys.exit(1)

    @vpn.command()
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    def status(interface: str) -> None:
        """Show VPN connection status."""
        if is_linux():
            result = subprocess.run(["wg", "show", interface], capture_output=True, text=True)
        elif is_macos():
            result = subprocess.run(["wg", "show"], capture_output=True, text=True)
        else:
            result = subprocess.run(["wg", "show"], capture_output=True, text=True)

        if result.returncode == 0 and result.stdout.strip():
            print(f"WireGuard interface [{interface}]:")
            print(result.stdout)
            vpn_ip = get_vpn_ip()
            if vpn_ip:
                print(f"VPN IP: {vpn_ip}")
        else:
            print(f"Not connected to VPN ({interface} is down or not configured)")

        print(f"\nConfig directory: {get_config_dir()}")

    @vpn.command()
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option("--interface", default="wg0", help="WireGuard interface name")
    @click.option(
        "--peer-id",
        envvar="ZEPGPU_PEER_ID",
        default=None,
        help="Peer UUID from join response (or saved in peer_state.json)",
    )
    def advertise(relay_url: str, interface: str, peer_id: str | None) -> None:
        """Advertise local GPUs to the relay server."""
        if not check_wireguard_installed():
            print("WireGuard is not installed.")
            install_wireguard()
            sys.exit(1)

        vpn_ip = get_vpn_ip()
        if not vpn_ip:
            print("Not connected to VPN. Run 'deepiri-gpu vpn join' first.", file=sys.stderr)
            sys.exit(1)

        resolved_peer = peer_id or load_peer_id()
        if not resolved_peer:
            print(
                "Missing peer id: pass --peer-id or ZEPGPU_PEER_ID, or join with --code to save it.",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Advertising GPUs to {relay_url}...")
        print(f"Your VPN IP: {vpn_ip}")
        print(f"GPU advertise server will run on port {vpn_settings.gpu_advertise_port}")
        print("Press Ctrl+C to stop advertising.")

        import httpx

        from deepiri_zepgpu.vpn.peer_node import discover_local_gpus

        async def advertise_loop() -> None:
            while True:
                gpus = discover_local_gpus()
                if gpus:
                    print(
                        f"  Found {len(gpus)} GPU(s): "
                        + ", ".join(f"{g.name} ({g.total_memory_mb}MB)" for g in gpus)
                    )
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(
                            vpn_api_url(relay_url, "/peers/heartbeat"),
                            json={
                                "peer_id": resolved_peer,
                                "gpu_status": [g.model_dump() for g in gpus],
                                "is_online": True,
                            },
                        )
                        print("  GPU status advertised to relay")
                except Exception as e:
                    print(f"  Failed to advertise: {e}")
                await asyncio.sleep(vpn_settings.heartbeat_interval_seconds)

        try:
            asyncio.run(advertise_loop())
        except KeyboardInterrupt:
            print("\nStopped advertising GPUs.")

    @vpn.command()
    def stop_advertise() -> None:
        """Stop advertising local GPUs."""
        print("GPU advertising stopped.")
        print("(In production, this would send an offline signal to the relay)")

    @vpn.command()
    @click.option("--relay-url", default=vpn_settings.relay_api_url, help="Relay server URL")
    @click.option(
        "--api-token",
        envvar="ZEPGPU_API_TOKEN",
        default=None,
        help="Bearer token (required to read gpu-pool from relay)",
    )
    def list_gpus(relay_url: str, api_token: str | None) -> None:
        """List GPUs available in the network pool."""
        import httpx

        if not api_token:
            print("list-gpus requires --api-token or ZEPGPU_API_TOKEN", file=sys.stderr)
            sys.exit(1)
        try:
            response = httpx.get(
                vpn_api_url(relay_url, "/gpu-pool"),
                headers={"Authorization": f"Bearer {api_token}"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            print("GPU Pool Summary:")
            print(f"  Total GPUs: {data['total_gpus']}")
            print(f"  Total Memory: {data['total_memory_mb'] // 1024}GB")
            print(f"  Available Memory: {data['available_memory_mb'] // 1024}GB")
            print(f"  Online Peers: {data['online_peers']}")
            print(f"  Online GPU Hosts: {data['online_gpu_hosts']}")
            print("\nGPU Breakdown:")
            for gpu in data.get("gpu_breakdown", []):
                print(
                    f"  [{gpu['username']}] {gpu['name']} - {gpu['total_memory_mb'] // 1024}GB - {gpu['state']}"
                )
        except Exception as e:
            print(f"Failed to fetch GPU pool: {e}", file=sys.stderr)
            sys.exit(1)


class VPNCLI:
    """VPN CLI command group."""

    @staticmethod
    def register(parent_cli: click.Group) -> None:
        if not HAS_CLICK:
            return
        parent_cli.add_command(vpn)


if __name__ == "__main__":
    vpn()
