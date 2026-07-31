from __future__ import annotations

import random
from types import SimpleNamespace

from deepiri_zepgpu.training.runner import _capture_rng_state, _restore_rng_state


class FakeTensor:
    def cpu(self) -> FakeTensor:
        return self


def test_python_torch_and_cuda_rng_state_restore() -> None:
    torch_state = FakeTensor()
    cuda_states = [FakeTensor(), FakeTensor()]
    restored: dict[str, object] = {}
    torch = SimpleNamespace(
        get_rng_state=lambda: torch_state,
        set_rng_state=lambda state: restored.__setitem__("torch", state),
        cuda=SimpleNamespace(
            get_rng_state_all=lambda: cuda_states,
            set_rng_state_all=lambda states: restored.__setitem__("cuda", states),
        ),
    )
    random.seed(2026)
    state = _capture_rng_state(torch)
    expected = random.random()
    random.random()
    _restore_rng_state(torch, state)
    assert random.random() == expected
    assert restored == {"torch": torch_state, "cuda": cuda_states}
