"""WireGuard configuration file generator."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Optional

from deepiri_zepgpu.vpn.config import vpn_settings


class WireGuardConfigGenerator:
    """Generate WireGuard .conf file content."""

    def __init__(
        self,
        vpn_ip: str,
        private_key: str,
        listen_port: int = 51820,
        dns: str = "1.1.1.1,8.8.8.8",
        mtu: int = 1420,
    ):
        self.vpn_ip = vpn_ip
        self.private_key = private_key
        self.listen_port = listen_port
        self.dns = dns
        self.mtu = mtu
        self._peers: list[dict] = []

    def add_peer(
        self,
        public_key: str,
        endpoint: Optional[str] = None,
        allowed_ips: str = "0.0.0.0/0, ::/0",
        persistent_keepalive: int = 25,
    ) -> "WireGuardConfigGenerator":
        self._peers.append({
            "public_key": public_key,
            "endpoint": endpoint,
            "allowed_ips": allowed_ips,
            "persistent_keepalive": persistent_keepalive,
        })
        return self

    def generate(self) -> str:
        lines = ["[Interface]"]
        lines.append(f"PrivateKey = {self.private_key}")
        lines.append(f"Address = {self.vpn_ip}/24")
        lines.append(f"ListenPort = {self.listen_port}")
        lines.append(f"DNS = {self.dns}")
        lines.append(f"MTU = {self.mtu}")
        lines.append("")

        for peer in self._peers:
            lines.append("[Peer]")
            lines.append(f"PublicKey = {peer['public_key']}")
            if peer["endpoint"]:
                lines.append(f"Endpoint = {peer['endpoint']}")
            lines.append(f"AllowedIPs = {peer['allowed_ips']}")
            if peer["persistent_keepalive"] > 0:
                lines.append(f"PersistentKeepalive = {peer['persistent_keepalive']}")
            lines.append("")

        return "\n".join(lines)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        path.write_text(self.generate())
        os.chmod(path, 0o600)


def allocate_vpn_ip(cidr: str = "10.8.0.0/24", used_ips: Optional[set[str]] = None) -> str:
    """Allocate the next available VPN IP in the CIDR range."""
    used = used_ips or set()
    net = ipaddress.ip_network(cidr)

    reserved = {str(net.network_address), str(net.broadcast_address)}
    for host in net.hosts():
        ip = str(host)
        if ip not in used and ip not in reserved:
            return ip

    raise RuntimeError(f"No available IPs in {cidr}")


def generate_relay_config(
    vpn_ip: str,
    private_key: str,
    listen_port: int = 51820,
) -> str:
    """Generate a relay server WireGuard config (no peers pre-configured)."""
    gen = WireGuardConfigGenerator(
        vpn_ip=vpn_ip,
        private_key=private_key,
        listen_port=listen_port,
    )
    return gen.generate()


def generate_peer_config(
    vpn_ip: str,
    private_key: str,
    relay_public_key: str,
    relay_endpoint: str,
    dns: str = "1.1.1.1,8.8.8.8",
) -> str:
    """Generate a peer WireGuard config pointing to the relay."""
    gen = WireGuardConfigGenerator(
        vpn_ip=vpn_ip,
        private_key=private_key,
        listen_port=0,
        dns=dns,
    )
    gen.add_peer(
        public_key=relay_public_key,
        endpoint=relay_endpoint,
        allowed_ips="0.0.0.0/0, ::/0",
        persistent_keepalive=25,
    )
    return gen.generate()
