"""Single-GPU LoRA/QLoRA runner with explicit optional dependencies."""

from __future__ import annotations

import random
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from importlib import import_module
from typing import Any

from deepiri_zepgpu.training.checkpoint import CheckpointMetadata, make_checkpoint_metadata
from deepiri_zepgpu.training.config import Precision, TrainingRunConfig
from deepiri_zepgpu.training.example import EXAMPLE_TEXTS
from deepiri_zepgpu.training.metrics import StepMetric, TrainingMetrics, runtime_versions


class MissingTrainingDependency(RuntimeError):
    pass


def _capture_rng_state(torch: Any) -> dict[str, Any]:
    return {
        "python_rng_state": random.getstate(),
        "torch_rng_state": torch.get_rng_state(),
        "cuda_rng_states": torch.cuda.get_rng_state_all(),
    }


def _restore_rng_state(torch: Any, state: dict[str, Any]) -> None:
    if "python_rng_state" in state:
        random.setstate(state["python_rng_state"])
    if "torch_rng_state" in state:
        torch.set_rng_state(state["torch_rng_state"].cpu())
    if "cuda_rng_states" in state:
        torch.cuda.set_rng_state_all([item.cpu() for item in state["cuda_rng_states"]])


def _imports() -> tuple[Any, Any, Any]:
    try:
        import peft
        import torch
        import transformers
    except ImportError as exc:
        raise MissingTrainingDependency(
            "Install optional training dependencies with `poetry install --with training`"
        ) from exc
    return torch, transformers, peft


class NvmlSampler:
    """Lazily initialized, failure-tolerant NVML sampler for one CUDA device."""

    def __init__(self, device_index: int) -> None:
        self.device_index = device_index
        self._module: Any | None = None
        self._handle: Any | None = None
        self._initialization_attempted = False
        self._initialized = False
        self._shutdown = False

    def _initialize(self) -> bool:
        if self._shutdown or self._initialization_attempted:
            return self._handle is not None
        self._initialization_attempted = True
        try:
            self._module = import_module("pynvml")
            self._module.nvmlInit()
            self._initialized = True
            self._handle = self._module.nvmlDeviceGetHandleByIndex(self.device_index)
        except Exception:
            self.shutdown()
            return False
        return True

    def sample(self) -> float | None:
        if not self._initialize():
            return None
        module = self._module
        if module is None:
            return None
        try:
            return float(module.nvmlDeviceGetUtilizationRates(self._handle).gpu)
        except Exception:
            return None

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        if self._initialized and self._module is not None:
            with suppress(Exception):
                self._module.nvmlShutdown()
        self._initialized = False
        self._handle = None


def _checkpoint(
    *,
    torch: Any,
    model: Any,
    optimizer: Any,
    config: TrainingRunConfig,
    run_id: str,
    step: int,
) -> CheckpointMetadata:
    directory = config.output_dir / f"checkpoint-{step}"
    adapter_dir = directory / "adapter"
    model.save_pretrained(adapter_dir)
    directory.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "step": step,
            "optimizer": optimizer.state_dict(),
            **_capture_rng_state(torch),
        },
        directory / "optimizer.pt",
    )
    metadata = make_checkpoint_metadata(
        run_id=run_id,
        step=step,
        directory=directory,
        config=config.model_dump(mode="json"),
    )
    metadata.save(directory)
    return metadata


def _seed_runtime(torch: Any, transformers: Any, seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    if hasattr(transformers, "set_seed"):
        transformers.set_seed(seed)


def _resolve_device(config: TrainingRunConfig, torch: Any) -> Any:
    try:
        device = torch.device(config.device)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"Invalid training device: {config.device}") from exc
    if device.type == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                f"CUDA device {config.device} was requested, but CUDA is unavailable"
            )
        device_index = 0 if device.index is None else device.index
        if device_index < 0 or device_index >= torch.cuda.device_count():
            raise ValueError(
                f"CUDA device index {device_index} is unavailable; "
                f"found {torch.cuda.device_count()} device(s)"
            )
        torch.cuda.set_device(device)
    elif config.load_in_4bit:
        raise RuntimeError("QLoRA 4-bit loading requires a CUDA device")
    return device


def _model_load_kwargs(
    config: TrainingRunConfig,
    torch: Any,
    transformers: Any,
    dtype: Any,
    device: Any,
) -> dict[str, Any]:
    transformers_major = int(str(transformers.__version__).split(".", 1)[0])
    dtype_argument = "dtype" if transformers_major >= 5 else "torch_dtype"
    kwargs: dict[str, Any] = {dtype_argument: dtype}
    if config.load_in_4bit:
        kwargs["device_map"] = {"": 0 if device.index is None else device.index}
        kwargs["quantization_config"] = transformers.BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        )
    return kwargs


def _move_optimizer_state(optimizer: Any, device: Any) -> None:
    for state in optimizer.state.values():
        for key, value in state.items():
            if hasattr(value, "to"):
                state[key] = value.to(device)


def _load_model(
    config: TrainingRunConfig,
    torch: Any,
    transformers: Any,
    peft: Any,
    run_id: str,
    device: Any,
) -> tuple[Any, Any, Any, int, str]:
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.model_name)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = {
        Precision.BF16: torch.bfloat16,
        Precision.FP16: torch.float16,
        Precision.FP32: torch.float32,
    }[config.precision]
    if (
        config.precision == Precision.BF16
        and device.type == "cuda"
        and not torch.cuda.is_bf16_supported()
    ):
        raise RuntimeError("bf16 precision is not supported by this CUDA device")
    model_kwargs = _model_load_kwargs(config, torch, transformers, dtype, device)
    model = transformers.AutoModelForCausalLM.from_pretrained(config.model_name, **model_kwargs)
    if config.load_in_4bit:
        if not bool(getattr(model, "is_loaded_in_4bit", False)):
            raise RuntimeError("QLoRA requires the base model to be loaded in 4-bit mode")
        model = peft.prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=config.gradient_checkpointing
        )
    elif config.gradient_checkpointing:
        model.gradient_checkpointing_enable()
    model.config.use_cache = False
    resume_path = config.resume_from
    resume_metadata = CheckpointMetadata.load(resume_path) if resume_path else None
    if resume_metadata and resume_path:
        model = peft.PeftModel.from_pretrained(model, resume_path / "adapter", is_trainable=True)
        run_id = resume_metadata.run_id
    else:
        model = peft.get_peft_model(
            model,
            peft.LoraConfig(
                r=config.lora.rank,
                lora_alpha=config.lora.alpha,
                lora_dropout=config.lora.dropout,
                target_modules=config.lora.target_modules or "all-linear",
                task_type=peft.TaskType.CAUSAL_LM,
            ),
        )
    if not config.load_in_4bit:
        model = model.to(device)
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=config.learning_rate,
    )
    start_step = 0
    if resume_metadata and resume_path:
        optimizer_state = torch.load(
            resume_path / "optimizer.pt", map_location=device, weights_only=True
        )
        if int(optimizer_state["step"]) != resume_metadata.step:
            raise ValueError("checkpoint optimizer step does not match checkpoint metadata")
        optimizer.load_state_dict(optimizer_state["optimizer"])
        _move_optimizer_state(optimizer, device)
        _restore_rng_state(torch, optimizer_state)
        start_step = int(optimizer_state["step"])
    return tokenizer, model, optimizer, start_step, run_id


def _train_steps(
    config: TrainingRunConfig,
    torch: Any,
    tokenizer: Any,
    model: Any,
    optimizer: Any,
    start_step: int,
    run_id: str,
    device: Any,
    nvml_sampler: NvmlSampler | None,
) -> list[StepMetric]:
    texts = config.dataset.texts or EXAMPLE_TEXTS
    encoded = tokenizer(
        texts,
        truncation=True,
        max_length=config.sequence_length,
        padding="max_length",
        return_tensors="pt",
    )
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    model.train()
    optimizer.zero_grad(set_to_none=True)
    step_metrics: list[StepMetric] = []
    for step in range(start_step + 1, config.max_steps + 1):
        step_started = time.perf_counter()
        token_count, sample_count, losses = _accumulate_step(
            config, model, encoded, texts, step, device
        )
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        elapsed = time.perf_counter() - step_started
        step_metrics.append(
            StepMetric(
                step=step,
                tokens=token_count,
                samples=sample_count,
                step_seconds=elapsed,
                compute_seconds=elapsed,
                loss=sum(losses) / len(losses),
                gpu_utilization_percent=(nvml_sampler.sample() if nvml_sampler else None),
            )
        )
        if step % config.checkpoint_every_steps == 0:
            _checkpoint(
                torch=torch,
                model=model,
                optimizer=optimizer,
                config=config,
                run_id=run_id,
                step=step,
            )
    return step_metrics


def _accumulate_step(
    config: TrainingRunConfig,
    model: Any,
    encoded: Any,
    texts: list[str],
    step: int,
    device: Any,
) -> tuple[int, int, list[float]]:
    token_count = 0
    sample_count = 0
    losses: list[float] = []
    for accumulation_index in range(config.gradient_accumulation_steps):
        offset = (
            (step - 1) * config.gradient_accumulation_steps * config.batch_size
            + accumulation_index * config.batch_size
        ) % len(texts)
        indices = [(offset + index) % len(texts) for index in range(config.batch_size)]
        non_blocking = device.type == "cuda"
        input_ids = encoded["input_ids"][indices].to(device, non_blocking=non_blocking)
        attention_mask = encoded["attention_mask"][indices].to(device, non_blocking=non_blocking)
        labels = input_ids.masked_fill(attention_mask == 0, -100)
        output = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
        loss = output.loss / config.gradient_accumulation_steps
        loss.backward()
        losses.append(float(loss.detach().item() * config.gradient_accumulation_steps))
        token_count += int(attention_mask.sum().item())
        sample_count += config.batch_size
    return token_count, sample_count, losses


def run_training(config: TrainingRunConfig) -> TrainingMetrics:
    """Run adapter fine-tuning on one explicitly configured device."""
    torch, transformers, peft = _imports()
    device = _resolve_device(config, torch)

    _seed_runtime(torch, transformers, config.seed)

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.write_json(config.output_dir / "config.json")

    tokenizer, model, optimizer, start_step, run_id = _load_model(
        config, torch, transformers, peft, run_id, device
    )
    nvml_sampler = (
        NvmlSampler(0 if device.index is None else device.index) if device.type == "cuda" else None
    )
    try:
        step_metrics = _train_steps(
            config,
            torch,
            tokenizer,
            model,
            optimizer,
            start_step,
            run_id,
            device,
            nvml_sampler,
        )
    finally:
        if nvml_sampler is not None:
            nvml_sampler.shutdown()

    final_dir = config.output_dir / "adapter-final"
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    _checkpoint(
        torch=torch,
        model=model,
        optimizer=optimizer,
        config=config,
        run_id=run_id,
        step=config.max_steps,
    )
    optional_versions: dict[str, Any] = {
        "torch": torch,
        "transformers": transformers,
        "peft": peft,
    }
    try:
        import accelerate

        optional_versions["accelerate"] = accelerate
    except ImportError:
        pass
    if config.load_in_4bit:
        try:
            import bitsandbytes

            optional_versions["bitsandbytes"] = bitsandbytes
        except ImportError:
            pass
    hardware: dict[str, Any] = {
        "device": str(device),
        "cuda": str(torch.version.cuda),
        "device_count": int(torch.cuda.device_count()),
    }
    peak_allocated_vram_bytes = 0
    peak_reserved_vram_bytes = 0
    if device.type == "cuda":
        device_index = 0 if device.index is None else device.index
        device_properties = torch.cuda.get_device_properties(device)
        hardware.update(
            {
                "device": torch.cuda.get_device_name(device),
                "compute_capability": ".".join(map(str, torch.cuda.get_device_capability(device))),
                "total_vram_bytes": int(device_properties.total_memory),
            }
        )
        peak_allocated_vram_bytes = int(torch.cuda.max_memory_allocated(device_index))
        peak_reserved_vram_bytes = int(torch.cuda.max_memory_reserved(device_index))
    metrics = TrainingMetrics(
        run_id=run_id,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        model=config.model_name,
        dataset=config.dataset.name,
        adapter_mode=config.adapter_mode.value,
        precision=config.precision.value,
        batch_size=config.batch_size,
        sequence_length=config.sequence_length,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        software_versions=runtime_versions(optional_versions),
        hardware=hardware,
        steps=step_metrics,
        peak_allocated_vram_bytes=peak_allocated_vram_bytes,
        peak_reserved_vram_bytes=peak_reserved_vram_bytes,
        artifact_ref=str(final_dir),
    )
    metrics.write_json(config.output_dir / "metrics.json")
    (config.output_dir / "summary.txt").write_text(metrics.summary() + "\n", encoding="utf-8")
    return metrics
