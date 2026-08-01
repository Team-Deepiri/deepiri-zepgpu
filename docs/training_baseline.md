# Phase 15-16 training foundation

Phases 15 and 16 provide a reproducible single-CUDA-device LoRA/QLoRA baseline and a
persistent-worker control/data plane. Training modules do not import the generic task router,
pickle, cloudpickle, or required ML packages at module import time.

## Single-GPU baseline

### Reference setup

- GPU: NVIDIA GeForce RTX 4050 Laptop GPU (6 GiB), compute capability 8.9.
- Verified minimum VRAM: 6 GiB for the included tiny LoRA and QLoRA smoke configurations.
- Tested runtime: Windows 11, Python 3.13.3, PyTorch 2.7.1+cu128, CUDA 12.8,
  Transformers 5.14.1, PEFT 0.20.0, Accelerate 1.14.0, and bitsandbytes 0.50.0.
- Checked-in LoRA result: `docs/baselines/phase15_tiny_lora_rtx4050.json` records 64.37
  tokens/s, 18,988,032 peak allocated VRAM bytes, and a zero communication ratio.
- A validation QLoRA run on the same GPU loaded the base model in NF4 4-bit mode and recorded
  192.94 tokens/s, 19,356,160 peak allocated VRAM bytes, and a zero communication ratio.

The tiny model is a harness regression target, not a model-quality benchmark. Throughput and GPU
utilization vary with thermals, background load, drivers, and package versions.

### Install and run

Install the optional group. On Windows, install the CUDA wheel selected for the host from the
official PyTorch wheel index; the default package resolver may otherwise install a CPU-only wheel.
The following is the exact tested CUDA 12.8 setup:

```console
poetry install --with dev,training
poetry run pip install --force-reinstall torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128
poetry run zepgpu-train examples/training/tiny_lora.json --smoke
poetry run zepgpu-train examples/training/tiny_qlora.json --smoke
```

Each output directory contains a resolved, recursively secret-filtered `config.json`, per-step
checkpoints, `adapter-final`, `metrics.json`, and `summary.txt`. QLoRA fails explicitly if the
Transformers/bitsandbytes stack does not report that the base model was loaded in 4-bit mode.
The explicit `device` setting defaults to `cuda:0`; requesting CUDA when it is unavailable or
selecting a nonexistent device index fails before model loading. This is still a single-device
baseline, not multi-GPU support. Non-quantized unit/smoke configurations may select `cpu` with a
CPU-compatible precision, while QLoRA retains Transformers/bitsandbytes-controlled CUDA placement.

Resume the optimizer, adapter, step counter, Python RNG, Torch RNG, and all CUDA RNG states:

```console
poetry run zepgpu-train examples/training/tiny_lora.json --smoke \
  --resume-from artifacts/training/tiny-lora-smoke/checkpoint-1
```

### Metric definitions

- `tokens_per_second` and `samples_per_second` divide useful items by total measured step time.
- `step_seconds` covers accumulation, backward, optimizer update, and the final CUDA completion
  barrier; `compute_seconds` is the useful single-node training duration within that interval.
- `sync_seconds`, `bytes_sent`, and `bytes_received` describe training-worker synchronization.
  They are exactly zero for this single-node baseline.
- `communication_compute_ratio` is `sync_seconds / useful_compute_seconds`, or zero when useful
  compute is zero. It is therefore exactly zero for a single-node run.
- Peak allocated and reserved VRAM come from Torch CUDA peak-memory counters. GPU utilization is
  sampled with NVML after each step. The maintained `nvidia-ml-py` distribution provides the
  `pynvml` import; `null` means NVML was unavailable rather than an invented value.
- JSON metrics also record model, dataset, adapter mode, precision, effective configuration,
  package/platform versions, CUDA version, device name/count, compute capability, and total VRAM.

## Persistent training runs

Training runs are first-class PostgreSQL records, separate from one-shot tasks, and link the room,
owner, assigned providers/workers, configuration, and artifacts. Legal states are `created`,
`preparing`, `ready`, `running`, `syncing`, `checkpointing`, `completed`, `failed`, `cancelled`, and
`timed_out`.

The public training API calls this scope `room_id`. It maps directly to the persisted VPN network
identifier, which database models name `vpn_network_id`; both names refer to the same room/network
scope in this subsystem.

Creating a run does not start it. Credential issuance prepares the run and establishes its startup
deadline. Each assigned worker authenticates, obtains only its own 15-minute room/run/worker/peer
credential, and reports `ready`. The run becomes `ready` only after every assigned worker is ready;
the owner must then call the explicit start endpoint. Terminal runs are immutable. Abort, startup
timeout, and first worker failure cancel nonterminal workers and revoke their run credentials; the
first failure reason remains authoritative.

Worker events persist event IDs, timestamps, progress, heartbeat time, round, restart count, state,
and error data. Stable event IDs make duplicate delivery idempotent. The concrete HTTP coordinator
client handles authentication, ready, heartbeat/progress, round, checkpoint, reconnect, shutdown,
and abort events. A worker buffers at most 1,000 ordered events during short outages by default,
tracks dropped events when full, retries with exponential backoff, and avoids replay after a
conflicting terminal event.

## Binary transport and relay

Every payload uses the versioned `ZEPTRN01` binary envelope. It includes UUID room, run, source
worker, and transfer scopes; synchronization round; nanosecond timestamp; payload type; tensor
shape and dtype; compression metadata; exact byte length; SHA-256 checksum; and extension bytes.
Scope, metadata, length, checksum, and duplicate-transfer conflicts are validated before use.

`TransferManager` attempts its abstract direct channel first. `PcclDirectChannel` accepts an async
sender callable whose inputs are the target worker ID and the unmodified binary envelope bytes.
The envelope scopes the room, run, source worker, and round. The sender owns direct-path timeout,
scope authorization/validation, any PCCL-specific metrics, and delivery acknowledgement before it
returns. It must remain non-blocking (or isolate a blocking binding itself). Only
`DirectUnavailable` or `TimeoutError` causes bounded retry and HTTP relay fallback; authentication,
validation, or other protocol errors propagate. This is an adapter boundary for a future PCCL
sender, not a bundled PCCL implementation. Tests use the same interface with two in-memory workers.

The production coordinator relay accepts and returns `application/octet-stream`, never JSON or
base64 model payloads. The sender performs begin, idempotent chunk upload, completion, and status
inspection. The assigned target separately downloads and acknowledges the envelope. Conflicting
duplicate chunks, cross-room/run/worker/round access, corruption, oversized payloads, and mutation
after completion are rejected. Transfer metrics report direct/relay path, encoded bytes, duration,
and retries.

Production relay state is shared through Redis using room/run/transfer-namespaced keys, per-transfer
locking, and TTL cleanup. Defaults are a 64 MiB transfer limit, 4 MiB coordinator chunk limit, and
300-second TTL; settings can override these bounds. Acknowledgement, abort, expiration cleanup, or
failed sender upload removes abandoned state. `BinaryRelayStore` is process-local and is only for
unit tests.

Training model/update bytes never use pickle, cloudpickle, JSON, base64, or the legacy task router.
Worker control events are JSON metadata over authenticated HTTP; they do not contain binary model
or optimizer payloads.

## Validation commands

With PostgreSQL on `127.0.0.1:5433` and Redis on `127.0.0.1:6380` from the test Compose file:

```console
poetry run pytest tests/training --collect-only -q
poetry run pytest tests/training -vv
poetry run pytest tests/training tests/integration tests/regression -vv
poetry run pytest tests -q
poetry run alembic heads
poetry run alembic upgrade head
poetry run alembic current
```

Run the optional CUDA integration test explicitly:

```console
ZEPGPU_RUN_GPU_TESTS=1 poetry run pytest tests/training/test_gpu_integration.py -vv
```

In PowerShell, use `$env:ZEPGPU_RUN_GPU_TESTS = "1"` before the pytest command.

## MVP limitations

- This phase is a single-GPU training baseline; it does not schedule or reserve multiple GPUs.
- Direct transport is an interface plus PCCL adapter boundary. Deployments must provide the actual
  PCCL/collective sender or use the coordinator relay.
- It does not implement production DiLoCo, compressed WAN optimization, FSDP islands, mixed-hardware
  planning, or overlay networking; those belong to later phases.
- Progress buffering is bounded in worker memory and targets short coordinator outages, not durable
  offline execution across process loss.
