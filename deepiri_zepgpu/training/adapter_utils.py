"""Shared LoRA/adapter tensor helpers for in-process and process workers."""

from __future__ import annotations

from typing import Any

import numpy as np


class AdapterStateError(RuntimeError):
    """Raised when adapter parameter sets diverge between snapshots."""


def adapter_state_dict(model: Any) -> dict[str, np.ndarray]:
    state: dict[str, np.ndarray] = {}
    for name, parameter in model.named_parameters():
        if parameter.requires_grad and "lora" in name.lower():
            state[name] = parameter.detach().float().cpu().numpy().astype(np.float32, copy=True)
    if not state:
        for name, parameter in model.named_parameters():
            if parameter.requires_grad:
                state[name] = parameter.detach().float().cpu().numpy().astype(np.float32, copy=True)
    return state


def apply_adapter_state(model: Any, averaged: dict[str, np.ndarray], torch: Any) -> None:
    with torch.no_grad():
        named = dict(model.named_parameters())
        for name, array in averaged.items():
            parameter = named.get(name)
            if parameter is None or not parameter.requires_grad:
                continue
            tensor = torch.as_tensor(array, device=parameter.device, dtype=parameter.dtype)
            parameter.copy_(tensor)


def adapters_equal(
    left: dict[str, np.ndarray], right: dict[str, np.ndarray], *, atol: float = 1e-5
) -> bool:
    if set(left) != set(right):
        return False
    return all(np.allclose(left[name], right[name], rtol=0.0, atol=atol) for name in left)


def delta_from_snapshots(
    before: dict[str, np.ndarray], after: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    if set(before) != set(after):
        raise AdapterStateError("adapter parameter set changed during local steps")
    return {name: (after[name] - before[name]).astype(np.float32) for name in before}
