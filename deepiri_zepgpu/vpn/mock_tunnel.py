"""Mock WireGuard tunnel for CI (no wg-quick required).

Allocates/persists a vpn_ip and marks the tunnel \"up\" in agent state so
control-plane and relay training paths can be exercised without a real kernel
interface. Real bring-up still uses ``vpn.cli.apply_wireguard_config``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from deepiri_zepgpu.vpn.wg_config import allocate_vpn_ip

DEFAULT_MOCK_STATE = Path.home() / ".zepgpu" / "wg_mock.json"


@dataclass
class MockTunnelState:
    room_id: str
    peer_id: str
    vpn_ip: str
    interface: str = "wg0-mock"
    up: bool = True
    config_path: str | None = None


def bring_up_mock_tunnel(
    *,
    room_id: str,
    peer_id: str,
    vpn_ip: str | None = None,
    cidr: str = "10.8.0.0/24",
    used_ips: set[str] | None = None,
    state_path: Path | None = None,
    config_text: str | None = None,
) -> MockTunnelState:
    """Persist a mock tunnel identity; optionally write config text beside state."""
    path = state_path or DEFAULT_MOCK_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    ip = vpn_ip or allocate_vpn_ip(cidr=cidr, used_ips=used_ips)
    conf_path = path.parent / "wg0-mock.conf"
    if config_text:
        conf_path.write_text(config_text, encoding="utf-8")
        os.chmod(conf_path, 0o600)
    state = MockTunnelState(
        room_id=room_id,
        peer_id=peer_id,
        vpn_ip=ip,
        config_path=str(conf_path) if config_text else None,
        up=True,
    )
    path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return state


def tear_down_mock_tunnel(state_path: Path | None = None) -> bool:
    path = state_path or DEFAULT_MOCK_STATE
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        conf = data.get("config_path")
        if conf:
            Path(conf).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def load_mock_tunnel(state_path: Path | None = None) -> MockTunnelState | None:
    path = state_path or DEFAULT_MOCK_STATE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return MockTunnelState(**data)
