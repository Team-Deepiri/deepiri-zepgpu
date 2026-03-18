"""Pipeline composition and chaining API."""

from __future__ import annotations

from typing import Any, Callable, Optional

from deepiri_zepgpu.core.pipeline_manager import PipelineStage, Pipeline, PipelineStageStatus
from deepiri_zepgpu.core.task import TaskResources, TaskPriority


class PipelineBuilder:
    """Builder for composing multi-stage GPU pipelines."""

    def __init__(self, name: str, user_id: Optional[str] = None):
        self._name = name
        self._user_id = user_id
        self._stages: list[PipelineStage] = []
        self._stage_names: set[str] = set()

    def add_stage(
        self,
        name: str,
        func: Callable[..., Any],
        args: Optional[dict[str, Any]] = None,
        depends_on: Optional[list[str]] = None,
        resources: Optional[TaskResources] = None,
        timeout_seconds: int = 3600,
        retry_count: int = 3,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> "PipelineBuilder":
        """Add a stage to the pipeline.

        Args:
            name: Unique name for this stage
            func: Function to execute for this stage
            args: Arguments template (use $stage_name to reference outputs)
            depends_on: List of stage names this depends on
            resources: GPU resources for this stage
            timeout_seconds: Stage timeout
            retry_count: Number of retries on failure
            on_error: Error handler function
        """
        if name in self._stage_names:
            raise ValueError(f"Stage '{name}' already exists")

        stage = PipelineStage(
            name=name,
            func=func,
            args_template=args or {},
            depends_on=depends_on or [],
            resources=resources,
            timeout_seconds=timeout_seconds,
            max_retries=retry_count,
            on_error=on_error,
        )

        self._stages.append(stage)
        self._stage_names.add(name)
        return self

    def preprocess(
        self,
        name: str = "preprocess",
        func: Callable[..., Any],
        args: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "PipelineBuilder":
        """Add a preprocessing stage (depends on nothing)."""
        return self.add_stage(
            name=name,
            func=func,
            args=args or kwargs,
            depends_on=[],
        )

    def compute(
        self,
        name: str,
        func: Callable[..., Any],
        args: Optional[dict[str, Any]] = None,
        depends_on: Optional[list[str]] = None,
        gpu_memory_mb: int = 2048,
        **kwargs: Any,
    ) -> "PipelineBuilder":
        """Add a GPU compute stage."""
        resources = TaskResources(gpu_memory_mb=gpu_memory_mb)
        return self.add_stage(
            name=name,
            func=func,
            args=args or kwargs,
            depends_on=depends_on,
            resources=resources,
        )

    def postprocess(
        self,
        name: str = "postprocess",
        func: Callable[..., Any],
        args: Optional[dict[str, Any]] = None,
        depends_on: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> "PipelineBuilder":
        """Add a postprocessing stage."""
        return self.add_stage(
            name=name,
            func=func,
            args=args or kwargs,
            depends_on=depends_on,
            resources=TaskResources(gpu_memory_mb=512),
        )

    def build(self) -> list[PipelineStage]:
        """Build and return the pipeline stages."""
        return list(self._stages)


class PipelineExecutor:
    """Execute composed pipelines."""

    def __init__(self, pipeline_manager: Any):
        self._manager = pipeline_manager

    async def run(
        self,
        stages: list[PipelineStage],
        user_id: Optional[str] = None,
        initial_inputs: Optional[dict[str, Any]] = None,
        name: Optional[str] = None,
    ) -> str:
        """Execute a pipeline and return pipeline ID."""
        pipeline_name = name or f"pipeline_{len(stages)}_stages"
        pipeline_id = await self._manager.create_pipeline(
            name=pipeline_name,
            stages=stages,
            user_id=user_id,
        )
        await self._manager.run_pipeline(pipeline_id, initial_inputs)
        return pipeline_id

    async def run_and_wait(
        self,
        stages: list[PipelineStage],
        user_id: Optional[str] = None,
        initial_inputs: Optional[dict[str, Any]] = None,
        name: Optional[str] = None,
        poll_interval: float = 0.5,
    ) -> dict[str, Any]:
        """Execute pipeline and wait for completion."""
        import asyncio

        pipeline_name = name or f"pipeline_{len(stages)}_stages"
        pipeline_id = await self._manager.create_pipeline(
            name=pipeline_name,
            stages=stages,
            user_id=user_id,
        )

        asyncio.create_task(self._manager.run_pipeline(pipeline_id, initial_inputs))

        while True:
            status = self._manager.get_pipeline_status(pipeline_id)
            if status["status"] in {"completed", "failed"}:
                return status
            await asyncio.sleep(poll_interval)


def create_inference_pipeline(
    preprocess_fn: Callable,
    model_fn: Callable,
    postprocess_fn: Callable,
    gpu_memory_mb: int = 4096,
) -> list[PipelineStage]:
    """Create a standard ML inference pipeline.

    Args:
        preprocess_fn: Data preprocessing function
        model_fn: Model inference function
        postprocess_fn: Output postprocessing function
        gpu_memory_mb: GPU memory for model inference

    Returns:
        List of pipeline stages
    """
    return PipelineBuilder("inference_pipeline").preprocess(
        name="preprocess",
        func=preprocess_fn,
    ).compute(
        name="inference",
        func=model_fn,
        depends_on=["preprocess"],
        gpu_memory_mb=gpu_memory_mb,
    ).postprocess(
        name="postprocess",
        func=postprocess_fn,
        depends_on=["inference"],
    ).build()


def create_simulation_pipeline(
    init_fn: Callable,
    step_fn: Callable,
    output_fn: Callable,
    num_steps: int,
    gpu_memory_mb: int = 4096,
) -> list[PipelineStage]:
    """Create a simulation pipeline with iterative steps.

    Args:
        init_fn: Initialize simulation state
        step_fn: Single simulation step function
        output_fn: Generate output from final state
        num_steps: Number of simulation steps
        gpu_memory_mb: GPU memory for simulation

    Returns:
        List of pipeline stages
    """
    builder = PipelineBuilder("simulation_pipeline")
    builder.add_stage(name="init", func=init_fn)

    for i in range(num_steps):
        builder.add_stage(
            name=f"step_{i}",
            func=step_fn,
            depends_on=[f"step_{i-1}" if i > 0 else "init"],
            gpu_memory_mb=gpu_memory_mb,
        )

    builder.add_stage(
        name="output",
        func=output_fn,
        depends_on=[f"step_{num_steps-1}"],
    )

    return builder.build()
