"""Task router - routes GPU tasks to remote peers over the VPN."""

from __future__ import annotations

import asyncio
import base64
import logging
import pickle
import time

import httpx

from deepiri_zepgpu.vpn.config import vpn_settings

logger = logging.getLogger(__name__)


class TaskRouter:
    """Route GPU tasks to remote peer nodes over the VPN."""

    def __init__(self, relay_api_url: str | None = None):
        self._relay_url = relay_api_url or vpn_settings.relay_api_url

    async def execute_on_peer(
        self,
        peer_vpn_ip: str,
        task_id: str,
        func,
        args: tuple,
        kwargs: dict,
        gpu_device_id: int,
        gpu_memory_mb: int,
        timeout_seconds: int = 3600,
        *,
        peer_id: str | None = None,
        network_id: str | None = None,
        consumer_account: str | None = None,
    ) -> dict:
        """Execute a function on a remote peer via its VPN IP."""
        func_encoded = base64.b64encode(pickle.dumps(func)).decode()
        args_encoded = base64.b64encode(pickle.dumps(args)).decode()
        kwargs_encoded = base64.b64encode(pickle.dumps(kwargs)).decode()

        async with httpx.AsyncClient(timeout=timeout_seconds + 10) as client:
            try:
                response = await client.post(
                    f"http://{peer_vpn_ip}:{vpn_settings.peer_server_port}/execute",
                    json={
                        "task_id": task_id,
                        "func_encoded": func_encoded,
                        "args_encoded": args_encoded,
                        "kwargs_encoded": kwargs_encoded,
                        "gpu_device_id": gpu_device_id,
                        "gpu_memory_mb": gpu_memory_mb,
                        "timeout_seconds": timeout_seconds,
                    },
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                result = response.json()
                if result.get("success") and result.get("attestation_signature"):
                    await self._ingest_peer_attestation(
                        result,
                        peer_id=peer_id or result.get("peer_id"),
                        network_id=network_id,
                        consumer_account=consumer_account,
                    )
                return result
            except httpx.TimeoutException:
                return {
                    "task_id": task_id,
                    "success": False,
                    "error": "Task timed out on remote peer",
                    "execution_time": timeout_seconds,
                }
            except Exception as e:
                return {
                    "task_id": task_id,
                    "success": False,
                    "error": str(e),
                    "execution_time": 0.0,
                }

    async def _ingest_peer_attestation(
        self,
        result: dict,
        *,
        peer_id: str | None,
        network_id: str | None,
        consumer_account: str | None,
    ) -> None:
        """Record peer-signed JOB_COMPLETED on the network-scoped ledger."""
        from deepiri_zepgpu.compute_ledger.service import LedgerService, new_signed_transaction
        from deepiri_zepgpu.compute_ledger.transaction import TxType
        from deepiri_zepgpu.config import settings
        from deepiri_zepgpu.database.session import get_db_context
        from deepiri_zepgpu.vpn.crypto import decrypt_value
        from deepiri_zepgpu.vpn.repositories import PeerRepository

        if not settings.ledger.enabled:
            return
        if not peer_id:
            return
        try:
            async with get_db_context() as db:
                peer_repo = PeerRepository(db)
                peer = await peer_repo.get_by_id(peer_id)
                if not peer or not peer.ledger_private_key_encrypted or not peer.ledger_public_key:
                    logger.debug("Peer %s missing ledger keys; skipping attestation", peer_id)
                    return
                priv = decrypt_value(peer.ledger_private_key_encrypted)
                scoped = network_id or str(peer.vpn_network_id)
                service = LedgerService(db, network_id=scoped)
                await service.ensure_initialized()
                nonce = (
                    await service.repo.get_max_nonce(service.chain_id, peer.ledger_public_key)
                ) + 1
                tx = new_signed_transaction(
                    private_key_b64=priv,
                    tx_type=TxType.JOB_COMPLETED,
                    nonce=nonce,
                    payload={
                        "task_id": result.get("task_id"),
                        "provider_account": peer.ledger_public_key,
                        "consumer_account": consumer_account or "remote-consumer",
                        "gpu_seconds": float(result.get("execution_time") or 0.0),
                        "input_hash": None,
                        "output_hash": result.get("result_digest"),
                        "peer_id": peer_id,
                        "attestation_signature": result.get("attestation_signature"),
                    },
                    sender=peer.ledger_public_key,
                )
                await service.submit_peer_attestation(
                    peer_public_key=peer.ledger_public_key,
                    signed_tx=tx,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ingest peer attestation for %s: %s", peer_id, exc)

    async def poll_task_result(
        self,
        peer_vpn_ip: str,
        task_id: str,
        poll_interval: float = 2.0,
        max_wait: float = 3600.0,
    ) -> dict | None:
        """Poll a remote peer for task result."""
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            while time.time() - start < max_wait:
                try:
                    response = await client.get(
                        f"http://{peer_vpn_ip}:{vpn_settings.peer_server_port}/result/{task_id}",
                        timeout=5,
                    )
                    if response.status_code == 200:
                        return response.json()
                    await asyncio.sleep(poll_interval)
                except Exception:
                    await asyncio.sleep(poll_interval)
        return None
