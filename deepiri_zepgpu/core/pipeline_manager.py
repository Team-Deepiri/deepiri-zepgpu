"""Pipeline manager for chaining and composing GPU tasks."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from deepiri_zepgpu.core.task import Task, TaskStatus


class PipelineStageStatus(Enum):
    """Status of a pipeline stage."""
    PENDING = "pending"
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStage:
    """Single stage in a pipeline."""
    name: str
    func: Callable[..., Any]
    args_template: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    resources: Optional[Any] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 3600
    on_error: Optional[Callable[[Exception], Any]] = None


@dataclass
class Pipeline:
    """Represents a multi-stage GPU compute pipeline."""
    name: str
    stages: list[PipelineStage]
    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: PipelineStageStatus = PipelineStageStatus.PENDING
    stage_results: dict[str, Any] = field(default_factory=dict)
    stage_statuses: dict[str, PipelineStageStatus] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    completed_stages: int = 0

    def __post_init__(self):
        for stage in self.stages:
            self.stage_statuses[stage.name] = PipelineStageStatus.PENDING


class PipelineManager:
    """Manages execution of multi-stage GPU pipelines."""

    def __init__(
        self,
        task_scheduler: Any,
        max_concurrent_stages: int = 4,
        enable_retry: bool = True,
    ):
        self._scheduler = task_scheduler
        self._max_concurrent_stages = max_concurrent_stages
        self._enable_retry = enable_retry

        self._pipelines: dict[str, Pipeline] = {}
        self._running_pipelines: dict[str, asyncio.Task] = {}
        self._stage_locks: dict[str, asyncio.Lock] = {}

    async def create_pipeline(
        self,
        name: str,
        stages: list[PipelineStage],
        user_id: Optional[str] = None,
    ) -> str:
        """Create a new pipeline."""
        pipeline = Pipeline(name=name, stages=stages, user_id=user_id)
        self._pipelines[pipeline.pipeline_id] = pipeline
        self._stage_locks[pipeline.pipeline_id] = asyncio.Lock()
        return pipeline.pipeline_id

    async def run_pipeline(
        self,
        pipeline_id: str,
        initial_inputs: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a pipeline."""
        pipeline = self._pipelines.get(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        pipeline.status = PipelineStageStatus.RUNNING
        initial_inputs = initial_inputs or {}

        try:
            results = await self._execute_stages(pipeline, initial_inputs)
            pipeline.status = PipelineStageStatus.COMPLETED
            return results

        except Exception as e:
            pipeline.status = PipelineStageStatus.FAILED
            raise

    async def _execute_stages(
        self,
        pipeline: Pipeline,
        initial_inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute pipeline stages respecting dependencies."""
        context = dict(initial_inputs)
        completed = set()
        failed_stages = set()

        stage_tasks: dict[str, asyncio.Task] = {}

        while len(completed) + len(failed_stages) < len(pipeline.stages):
            ready_stages = self._get_ready_stages(
                pipeline, completed, failed_stages, context
            )

            if not ready_stages and len(stage_tasks) == 0:
                break

            for stage in ready_stages[:self._max_concurrent_stages - len(stage_tasks)]:
                task = asyncio.create_task(
                    self._execute_stage(pipeline, stage, context)
                )
                stage_tasks[stage.name] = task

            if stage_tasks:
                done, _ = await asyncio.wait(
                    stage_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for completed_task in done:
                    stage_name = None
                    for name, t in list(stage_tasks.items()):
                        if t == completed_task:
                            stage_name = name
                            break

                    if stage_name:
                        stage_tasks.pop(stage_name)
                        try:
                            result = completed_task.result()
                            context[stage_name] = result
                            completed.add(stage_name)
                            pipeline.completed_stages += 1
                        except Exception as e:
                            failed_stages.add(stage_name)
                            pipeline.errors[stage_name] = str(e)
                            if not self._enable_retry:
                                raise

        return context

    def _get_ready_stages(
        self,
        pipeline: Pipeline,
        completed: set[str],
        failed: set[str],
        context: dict[str, Any],
    ) -> list[PipelineStage]:
        """Get stages that are ready to execute."""
        ready = []
        for stage in pipeline.stages:
            if stage.name in completed or stage.name in failed:
                continue

            deps_met = all(dep in completed for dep in stage.depends_on)
            if deps_met:
                ready.append(stage)

        return ready

    async def _execute_stage(
        self,
        pipeline: Pipeline,
        stage: PipelineStage,
        context: dict[str, Any],
    ) -> Any:
        """Execute a single pipeline stage."""
        async with self._stage_locks[pipeline.pipeline_id]:
            pipeline.stage_statuses[stage.name] = PipelineStageStatus.RUNNING

        try:
            resolved_args = self._resolve_args(stage.args_template, context)

            if asyncio.iscoroutinefunction(stage.func):
                result = await stage.func(**resolved_args)
            else:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: stage.func(**resolved_args)
                )

            async with self._stage_locks[pipeline.pipeline_id]:
                pipeline.stage_statuses[stage.name] = PipelineStageStatus.COMPLETED
                pipeline.stage_results[stage.name] = result

            return result

        except Exception as e:
            async with self._stage_locks[pipeline.pipeline_id]:
                pipeline.stage_statuses[stage.name] = PipelineStageStatus.FAILED

            if stage.retry_count < stage.max_retries:
                stage.retry_count += 1
                return await self._execute_stage(pipeline, stage, context)

            if stage.on_error:
                return stage.on_error(e)

            raise

    def _resolve_args(
        self,
        template: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve argument template using context values."""
        resolved = {}
        for key, value in template.items():
            if isinstance(value, str) and value.startswith("$"):
                resolved[key] = context.get(value[1:])
            else:
                resolved[key] = value
        return resolved

    def get_pipeline(self, pipeline_id: str) -> Optional[Pipeline]:
        """Get pipeline by ID."""
        return self._pipelines.get(pipeline_id)

    def get_pipeline_status(self, pipeline_id: str) -> dict[str, Any]:
        """Get detailed pipeline status."""
        pipeline = self._pipelines.get(pipeline_id)
        if not pipeline:
            return {"error": "Pipeline not found"}

        return {
            "pipeline_id": pipeline.pipeline_id,
            "name": pipeline.name,
            "status": pipeline.status.value,
            "stages": {
                name: status.value
                for name, status in pipeline.stage_statuses.items()
            },
            "completed_stages": pipeline.completed_stages,
            "total_stages": len(pipeline.stages),
            "errors": pipeline.errors,
        }

    def cancel_pipeline(self, pipeline_id: str) -> bool:
        """Cancel a running pipeline."""
        task = self._running_pipelines.get(pipeline_id)
        if task:
            task.cancel()
            return True
        return False

    def list_pipelines(
        self,
        user_id: Optional[str] = None,
        status: Optional[PipelineStageStatus] = None,
    ) -> list[Pipeline]:
        """List pipelines with optional filtering."""
        pipelines = list(self._pipelines.values())
        if user_id:
            pipelines = [p for p in pipelines if p.user_id == user_id]
        if status:
            pipelines = [p for p in pipelines if p.status == status]
        return sorted(pipelines, key=lambda p: p.created_at, reverse=True)
