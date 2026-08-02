"""Validation and delivery for untrusted task callback URLs."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import SplitResult, urlsplit

import httpx

from deepiri_zepgpu.config import settings

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class CallbackURLValidationError(ValueError):
    """A callback URL is malformed or targets a prohibited destination."""


class CallbackDeliveryError(RuntimeError):
    """A validated callback could not be delivered safely."""


def _normalize_hostname(hostname: str) -> str:
    candidate = hostname.rstrip(".").lower()
    if not candidate or "%" in candidate:
        raise CallbackURLValidationError("callback host is missing or malformed")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        try:
            candidate = candidate.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise CallbackURLValidationError("callback host is malformed") from exc
        if len(candidate) > 253 or any(
            not _HOST_LABEL.fullmatch(label) for label in candidate.split(".")
        ):
            raise CallbackURLValidationError("callback host is malformed") from None
        return candidate
    return address.compressed


def _is_localhost_name(hostname: str) -> bool:
    return hostname == "localhost" or hostname.endswith(".localhost")


def _allowed_host(hostname: str, allowed_hosts: Iterable[str]) -> bool:
    for configured in allowed_hosts:
        pattern = configured.strip().lower().rstrip(".")
        if not pattern:
            continue
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if hostname.endswith(suffix) and hostname != suffix[1:]:
                return True
        elif hostname == _normalize_hostname(pattern):
            return True
    return False


def _blocked_address_reason(address: IPAddress) -> str | None:
    candidate: IPAddress = address.ipv4_mapped or address if address.version == 6 else address
    if candidate.is_loopback:
        return "loopback"
    if candidate.is_private:
        return "private"
    if candidate.is_link_local:
        return "link-local"
    if candidate.is_multicast:
        return "multicast"
    if candidate.is_unspecified:
        return "unspecified"
    if candidate.is_reserved or not candidate.is_global:
        return "reserved or non-public"
    return None


async def resolve_callback_addresses(hostname: str, port: int) -> tuple[IPAddress, ...]:
    """Resolve every address currently advertised for a callback host."""
    try:
        return (ipaddress.ip_address(hostname),)
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        answers = await loop.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise CallbackURLValidationError("callback host could not be resolved") from exc

    addresses: list[IPAddress] = []
    for _family, _type, _protocol, _canonical_name, sockaddr in answers:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise CallbackURLValidationError("callback DNS returned a malformed address") from exc
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise CallbackURLValidationError("callback host did not resolve to an address")
    return tuple(addresses)


def _parse_callback_url(callback_url: str) -> tuple[SplitResult, str, str, int]:
    if not callback_url or callback_url != callback_url.strip() or len(callback_url) > 500:
        raise CallbackURLValidationError("callback URL is missing, malformed, or too long")
    try:
        parsed = urlsplit(callback_url)
        port = parsed.port
    except ValueError as exc:
        raise CallbackURLValidationError("callback URL is malformed") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise CallbackURLValidationError("callback URL scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise CallbackURLValidationError("callback URL must not contain credentials")
    if not parsed.hostname:
        raise CallbackURLValidationError("callback host is missing or malformed")
    if parsed.fragment:
        raise CallbackURLValidationError("callback URL must not contain a fragment")
    if port == 0:
        raise CallbackURLValidationError("callback URL port must be between 1 and 65535")
    return (
        parsed,
        scheme,
        _normalize_hostname(parsed.hostname),
        port or (443 if scheme == "https" else 80),
    )


def _development_localhost_allowed(
    hostname: str,
    *,
    allow_localhost: bool | None,
    environment: str,
) -> bool:
    localhost_opt_in = (
        settings.task_callback_allow_localhost if allow_localhost is None else allow_localhost
    )
    return localhost_opt_in and environment == "development" and _is_localhost_name(hostname)


async def validate_callback_url(
    callback_url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    allow_localhost: bool | None = None,
    environment: str | None = None,
) -> str:
    """Validate syntax, policy, DNS answers, and address scope for a callback URL."""
    _parsed, scheme, hostname, port = _parse_callback_url(callback_url)
    current_environment = environment or settings.environment
    if current_environment == "production" and scheme != "https":
        raise CallbackURLValidationError("production callbacks must use https")

    configured_hosts = (
        tuple(allowed_hosts)
        if allowed_hosts is not None
        else settings.parsed_task_callback_allowed_hosts()
    )
    allow_development_localhost = _development_localhost_allowed(
        hostname,
        allow_localhost=allow_localhost,
        environment=current_environment,
    )

    if (
        configured_hosts
        and not _allowed_host(hostname, configured_hosts)
        and not allow_development_localhost
    ):
        raise CallbackURLValidationError("callback host is not in TASK_CALLBACK_ALLOWED_HOSTS")
    if _is_localhost_name(hostname) and not allow_development_localhost:
        raise CallbackURLValidationError("localhost callbacks are disabled")

    addresses = await resolve_callback_addresses(hostname, port)
    for address in addresses:
        reason = _blocked_address_reason(address)
        if reason and not (allow_development_localhost and reason == "loopback"):
            raise CallbackURLValidationError(
                f"callback host resolves to a prohibited {reason} address"
            )
    return callback_url


async def deliver_callback(callback_url: str, payload: Mapping[str, Any]) -> None:
    """Revalidate and deliver a callback without redirects, proxies, or response buffering."""
    validated_url = await validate_callback_url(callback_url)
    timeout = httpx.Timeout(
        connect=settings.task_callback_connect_timeout_seconds,
        read=settings.task_callback_read_timeout_seconds,
        write=settings.task_callback_write_timeout_seconds,
        pool=settings.task_callback_pool_timeout_seconds,
    )
    try:
        async with (
            httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream("POST", validated_url, json=dict(payload)) as response,
        ):
            if response.is_redirect:
                raise CallbackDeliveryError(
                    "callback returned a redirect; redirects are not followed"
                )
            response.raise_for_status()
    except CallbackDeliveryError:
        raise
    except httpx.HTTPError as exc:
        raise CallbackDeliveryError(f"callback HTTP delivery failed: {exc}") from exc
