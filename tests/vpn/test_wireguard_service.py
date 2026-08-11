"""WireGuard config and mock-tunnel unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepiri_zepgpu.vpn.mock_tunnel import (
    bring_up_mock_tunnel,
    load_mock_tunnel,
    tear_down_mock_tunnel,
)
from deepiri_zepgpu.vpn.wg_config import (
    WireGuardConfigGenerator,
    allocate_vpn_ip,
    allowed_ips_for_cidr,
    generate_relay_config,
)


@pytest.mark.unit
def test_allowed_ips_default_is_room_cidr() -> None:
    gen = WireGuardConfigGenerator(vpn_ip="10.8.0.2", private_key="PRIV")
    gen.add_peer(public_key="PUB", endpoint="1.2.3.4:51820")
    text = gen.generate()
    assert "AllowedIPs = 10.8.0.0/24" in text
    assert "0.0.0.0/0" not in text
    assert "PersistentKeepalive = 25" in text


@pytest.mark.unit
def test_allocate_vpn_ip_skips_used() -> None:
    ip = allocate_vpn_ip(used_ips={"10.8.0.1", "10.8.0.2"})
    assert ip == "10.8.0.3"


@pytest.mark.unit
def test_hub_regen_adds_and_removes_peers() -> None:
    assert allowed_ips_for_cidr("10.9.0.0/24") == "10.9.0.0/24"
    with_peer = generate_relay_config(
        "10.8.0.1",
        "HUBPRIV",
        peers=[("PEERPUB", "10.8.0.2")],
        allowed_ips="10.8.0.0/24",
    )
    assert "PEERPUB" in with_peer
    assert "10.8.0.2" in with_peer
    without = generate_relay_config("10.8.0.1", "HUBPRIV", peers=[])
    assert "PEERPUB" not in without


@pytest.mark.unit
def test_mock_tunnel_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "wg_mock.json"
    state = bring_up_mock_tunnel(
        room_id="room",
        peer_id="peer",
        vpn_ip="10.8.0.9",
        state_path=state_path,
        config_text="[Interface]\nPrivateKey = x\n",
    )
    assert state.up is True
    loaded = load_mock_tunnel(state_path)
    assert loaded is not None
    assert loaded.vpn_ip == "10.8.0.9"
    assert tear_down_mock_tunnel(state_path) is True
    assert load_mock_tunnel(state_path) is None


@pytest.mark.unit
def test_windows_export_does_not_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deepiri_zepgpu.vpn import cli as vpn_cli

    monkeypatch.setattr(vpn_cli, "get_config_dir", lambda: tmp_path)
    conf = vpn_cli.export_wireguard_config("[Interface]\nPrivateKey = x\n", "wg0")
    assert conf == tmp_path / "wg0.conf"
    assert "PrivateKey" in conf.read_text(encoding="utf-8")
    text = vpn_cli.windows_import_instructions(conf)
    assert "Import tunnel" in text
    assert "zepgpu-node serve" in text
    assert str(conf) in text
