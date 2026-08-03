# SPDX attribution for vendored DeMo algorithm pieces.
#
# Upstream: https://github.com/bloc97/DeMo (bloc97/DeMo)
# Paper: DeMo: Decoupled Momentum Optimization, arXiv:2411.19870
#
# `demo_upstream.py` is the upstream standalone optimizer for reference.
# `dct.py` adapts TransformDCT / CompressDCT / DCT helpers for ZepGPU's
# binary WAN exchange without requiring einops or torch.distributed.
#
# Future DeMo updates should be reviewed against demo_upstream.py and
# ported carefully into dct.py / demo_backend.py.
