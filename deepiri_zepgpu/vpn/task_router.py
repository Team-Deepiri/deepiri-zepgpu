"""Task router - routes GPU tasks to remote peers over the VPN."""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

import httpx

from deepiri_zepgpu.vpn.config import vpn_settings
from deepiri_zepgpu.vpn.peer_protocol import (
    MAX_ENCODED_MESSAGE_SIZE,
    TaskResultMessage,
    create_execute_message,
    decode_message,
    encode_message,
    normalize_uuid,
    validate_protocol_secret,
)

logger = logging.getLogger(__name__)


class TaskRouter:
    """Route fixed, authenticated primitive operations to WireGuard peers."""

    def __init__(
        self,
        *,
        room_id: str,
        sender_peer_id: str,
        recipient_peer_id: str,
        auth_token: str,
        relay_api_url: str | None = None,
    ) -> None:
        self._relay_url = relay_api_url or vpn_settings.relay_api_url
        self._room_id = normalize_uuid(room_id, "room_id")
        self._sender_peer_id = normalize_uuid(sender_peer_id, "sender_peer_id")
        self._recipient_peer_id = normalize_uuid(recipient_peer_id, "recipient_peer_id")
        validate_protocol_secret(auth_token)
        self._auth_token = auth_token

    async def execute_on_peer(
        self,
        peer_vpn_ip: str,
        task_id: str,
        gpu_device_id: int,
        gpu_memory_mb: int,
        timeout_seconds: int = 3600,
        *,
        message: str = "remote noop completed",
        peer_id: str | None = None,
        network_id: str | None = None,
        consumer_account: str | None = None,
    ) -> dict:
        """Execute the fixed no-op operation; arbitrary callables are not accepted."""
        normalized_task_id = normalize_uuid(task_id, "task_id")
        request_message = create_execute_message(
            secret=self._auth_token,
            message_id=str(uuid4()),
            room_id=self._room_id,
            sender_peer_id=self._sender_peer_id,
            recipient_peer_id=self._recipient_peer_id,
            task_id=normalized_task_id,
            issued_at=int(time.time()),
            gpu_device_id=gpu_device_id,
            gpu_memory_mb=gpu_memory_mb,
            timeout_seconds=timeout_seconds,
            message=message,
        )

        async with httpx.AsyncClient(timeout=timeout_seconds + 10) as client:
            try:
                response = await client.post(
                    f"http://{peer_vpn_ip}:{vpn_settings.peer_server_port}/execute",
                    content=encode_message(request_message),
                    headers={
                        "Authorization": f"Bearer {self._auth_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                if len(response.content) > MAX_ENCODED_MESSAGE_SIZE:
                    raise ValueError("Peer result exceeds the maximum message size")
                decoded = decode_message(
                    response.content,
                    secret=self._auth_token,
                    expected_kind="task.result",
                )
                if not isinstance(decoded, TaskResultMessage):
                    raise ValueError("Peer returned an unexpected message kind")
                if (
                    decoded.request_message_id != request_message.message_id
                    or decoded.task_id != normalized_task_id
                    or decoded.room_id != self._room_id
                    or decoded.sender_peer_id != self._recipient_peer_id
                    or decoded.recipient_peer_id != self._sender_peer_id
                ):
                    raise ValueError("Peer result scope or correlation does not match the request")
                result = decoded.model_dump(mode="json")
                if result.get("success") and result.get("attestation_signature"):
                    await self._ingest_peer_attestation(
                        result,
                        peer_id=peer_id or decoded.sender_peer_id,
                        network_id=network_id,
                        consumer_account=consumer_account,
                    )
                return result  # type: ignore[no-any-return]
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
                        headers={"Authorization": f"Bearer {self._auth_token}"},
                        timeout=5,
                    )
                    if response.status_code == 200:
                        if len(response.content) > MAX_ENCODED_MESSAGE_SIZE:
                            raise ValueError("Peer result exceeds the maximum message size")
                        decoded = decode_message(
                            response.content,
                            secret=self._auth_token,
                            expected_kind="task.result",
                        )
                        if not isinstance(decoded, TaskResultMessage):
                            raise ValueError("Peer returned an unexpected message kind")
                        if (
                            decoded.task_id != normalize_uuid(task_id, "task_id")
                            or decoded.room_id != self._room_id
                            or decoded.sender_peer_id != self._recipient_peer_id
                            or decoded.recipient_peer_id != self._sender_peer_id
                        ):
                            raise ValueError("Peer result scope does not match the request")
                        return decoded.model_dump(mode="json")
                    await asyncio.sleep(poll_interval)
                except Exception:
                    await asyncio.sleep(poll_interval)
        return None
