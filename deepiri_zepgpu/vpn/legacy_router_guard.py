"""Guards for the legacy pickle TaskRouter (WireGuard-only; no training use)."""

from __future__ import annotations

import inspect
from typing import Final

from deepiri_zepgpu.rooms.transport import (
    LEGACY_PICKLE_ALLOWED_TRANSPORTS,
    allows_legacy_pickle_router,
)

TRAINING_PACKAGE_PREFIX: Final = "deepiri_zepgpu.training"


class LegacyRouterForbiddenError(RuntimeError):
    """Raised when legacy pickle routing is not allowed for the current context."""


def assert_legacy_pickle_router_allowed(transport_mode: str | None) -> None:
    """Quarantine: pickle TaskRouter may only run on WireGuard rooms."""

    if allows_legacy_pickle_router(transport_mode):
        return
    allowed = ", ".join(sorted(LEGACY_PICKLE_ALLOWED_TRANSPORTS))
    raise LegacyRouterForbiddenError(
        f"Legacy pickle TaskRouter is WireGuard-only "
        f"(allowed transports: {allowed}); "
        f"got transport_mode={transport_mode!r}. "
        "Use dial-out node-task assignment for non-WireGuard rooms."
    )


def assert_not_called_from_training() -> None:
    """Prevent training modules from invoking the legacy pickle router."""

    for frame_info in inspect.stack():
        module = frame_info.frame.f_globals.get("__name__", "") or ""
        if module == TRAINING_PACKAGE_PREFIX or module.startswith(f"{TRAINING_PACKAGE_PREFIX}."):
            raise LegacyRouterForbiddenError(
                "Training code must not use the legacy pickle TaskRouter; "
                "use the binary training data plane instead."
            )
