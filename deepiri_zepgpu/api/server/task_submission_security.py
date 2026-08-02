"""Authorization and trust-boundary checks for persisted task submissions."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import HTTPException, status

from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.queue.safe_task import (
    UnsafeTaskPayloadError,
    encode_task_arguments,
    validate_operation,
)

logger = logging.getLogger(__name__)

_TASK_SUBMITTER_ROLES = {"admin", "researcher"}


async def validate_submitted_callback(callback_url: str | None) -> str | None:
    """Map centralized callback validation failures to a client-safe API error."""
    if callback_url is None:
        return None
    from deepiri_zepgpu.security.callbacks import (
        CallbackURLValidationError,
        validate_callback_url,
    )

    try:
        return await validate_callback_url(callback_url)
    except CallbackURLValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid callback URL: {exc}",
        ) from exc


def require_task_submitter(user: User | None) -> User:
    """Require an authenticated elevated role for persisted worker execution."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    role = getattr(user.role, "value", user.role)
    if role not in _TASK_SUBMITTER_ROLES:
        logger.warning("Rejected task submission from non-elevated user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Task submission requires the researcher role",
        )
    return user


def prepare_task_payload(
    *,
    user: User | None,
    func_name: str | None,
    serialized_func: str | None,
    args: Sequence[Any] | None,
    kwargs: Mapping[str, Any] | None,
) -> tuple[User, str, bytes, bytes]:
    """Authorize and encode a non-executable task payload for persistence."""
    authorized_user = require_task_submitter(user)
    try:
        operation = validate_operation(func_name, serialized_func)
        encoded_args, encoded_kwargs = encode_task_arguments(args, kwargs)
    except UnsafeTaskPayloadError as exc:
        logger.warning("Rejected unsafe task submission from user %s: %s", authorized_user.id, exc)
        code = status.HTTP_410_GONE if serialized_func else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return authorized_user, operation, encoded_args, encoded_kwargs
