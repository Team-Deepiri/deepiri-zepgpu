"""Celery tasks for distributed GPU task execution."""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Any

import cloudpickle
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from deepiri_zepgpu.database.session import get_db_context
from deepiri_zepgpu.database.repositories import (
    TaskRepository,
    PipelineRepository,
    GPURepository,
    AuditRepository,
    ScheduleRepository,
    ScheduleRunRepository,
)
from deepiri_zepgpu.database.models.audit_log import AuditAction
from deepiri_zepgpu.database.models.task import Task as DBTask, TaskPriority, TaskStatus
from deepiri_zepgpu.database.models.scheduled_task_run import ScheduleRunStatus
from deepiri_zepgpu.database.models.gang_scheduling import GangStatus
from deepiri_zepgpu.queue.celery_app import celery_app
from deepiri_zepgpu.storage.result_store import ResultStore

logger = logging.getLogger(__name__)


class GPUTask(Task):
    """Base task class for GPU operations."""
    
    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        """Handle task failure."""
        logger.error(f"Task {task_id} failed: {exc}")
        asyncio.run(_mark_task_failed(task_id, str(exc), traceback.format_exc()))
        asyncio.run(_execute_callback(task_id, "failed"))
    
    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        """Handle task success."""
        logger.info(f"Task {task_id} succeeded")
        asyncio.run(_execute_callback(task_id, "completed"))


async def _execute_callback(task_id: str, status: str) -> None:
    """Execute callback webhook if configured."""
    import httpx
    
    async with get_db_context() as db:
        repo = TaskRepository(db)
        task = await repo.get_by_id(task_id)
        
        if not task or not task.callback_url:
            return
        
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    task.callback_url,
                    json={
                        "task_id": task_id,
                        "status": status,
                        "user_id": task.user_id,
                    },
                    timeout=10.0,
                )
                logger.info(f"Callback executed for task {task_id}")
        except Exception as e:
            logger.warning(f"Callback failed for task {task_id}: {e}")


async def _mark_task_failed(task_id: str, error: str, tb: str) -> None:
    """Mark task as failed in database."""
    async with get_db_context() as db:
        repo = TaskRepository(db)
        await repo.mark_failed(task_id, error, tb)


async def _log_audit(
    action: AuditAction,
    task_id: str,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log an audit entry."""
    async with get_db_context() as db:
        audit_repo = AuditRepository(db)
        await audit_repo.log_task_action(
            action=action,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )


@celery_app.task(
    bind=True,
    base=GPUTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=3600,
    time_limit=3700,
)
def execute_task(self, task_id: str) -> dict[str, Any]:
    """Execute a GPU task.
    
    Args:
        task_id: The ID of the task to execute
        
    Returns:
        Dictionary with execution results
    """
    logger.info(f"Starting execution of task {task_id}")
    
    async def _execute() -> dict[str, Any]:
        async with get_db_context() as db:
            repo = TaskRepository(db)
            gpu_repo = GPURepository(db)
            
            task = await repo.get_by_id(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return {"status": "error", "message": "Task not found"}
            
            await repo.mark_running(task_id)
            await _log_audit(AuditAction.TASK_START, task_id, task.user_id)
            
            gpu_device_id = None
            gpu_device = None
            
            if task.gpu_memory_mb > 0:
                available_gpus = await gpu_repo.list_available()
                for device in available_gpus:
                    if device.total_memory_mb and device.available_memory_mb:
                        if device.available_memory_mb >= task.gpu_memory_mb:
                            gpu_device = await gpu_repo.allocate(device.device_index, task_id)
                            if gpu_device:
                                gpu_device_id = gpu_device.device_index
                                await repo.update_status(task_id, task.status, gpu_device_id=gpu_device_id)
                                logger.info(f"Allocated GPU {gpu_device_id} to task {task_id}")
                                break
                
                if gpu_device is None and not task.allow_fallback_cpu:
                    await repo.mark_failed(task_id, "No GPU available", "")
                    await _log_audit(AuditAction.TASK_FAIL, task_id, task.user_id, {"error": "No GPU available"})
                    return {"status": "error", "message": "No GPU available"}
            
            try:
                import os
                if gpu_device_id is not None:
                    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_device_id)
                
                result = None
                
                if task.serialized_func:
                    func = cloudpickle.loads(task.serialized_func)
                    func_args = cloudpickle.loads(task.args) if task.args else ()
                    func_kwargs = cloudpickle.loads(task.kwargs) if task.kwargs else {}
                    result = func(*func_args, **func_kwargs)
                elif task.func_name:
                    module_name, func_name = task.func_name.rsplit(".", 1)
                    import importlib
                    module = importlib.import_module(module_name)
                    func = getattr(module, func_name)
                    func_args = cloudpickle.loads(task.args) if task.args else ()
                    func_kwargs = cloudpickle.loads(task.kwargs) if task.kwargs else {}
                    result = func(*func_args, **func_kwargs)
                
                if result is not None:
                    result_bytes = cloudpickle.dumps(result)
                    result_store = ResultStore()
                    await result_store.store_result(task_id, result_bytes)
                    await repo.mark_completed(task_id, execution_time_ms=0)
                else:
                    await repo.mark_completed(task_id)
                
                await _log_audit(AuditAction.TASK_COMPLETE, task_id, task.user_id)
                
                logger.info(f"Task {task_id} completed successfully")
                return {
                    "status": "success",
                    "task_id": task_id,
                    "gpu_device_id": gpu_device_id,
                }
                    
            except SoftTimeLimitExceeded:
                logger.error(f"Task {task_id} timed out")
                await repo.mark_timeout(task_id)
                await _log_audit(AuditAction.TASK_FAIL, task_id, task.user_id, {"error": "Timeout"})
                return {"status": "error", "message": "Task timed out"}
                
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                await repo.mark_failed(task_id, str(e), traceback.format_exc())
                await _log_audit(AuditAction.TASK_FAIL, task_id, task.user_id, {"error": str(e)})
                raise
                
            finally:
                if gpu_device_id is not None:
                    await gpu_repo.release(gpu_device_id)
                    await _log_audit(AuditAction.GPU_RELEASE, task_id, task.user_id, {"device_id": gpu_device_id})
                    logger.info(f"Released GPU {gpu_device_id} from task {task_id}")
    
    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=GPUTask,
    soft_time_limit=7200,
    time_limit=7300,
)
def execute_pipeline(self, pipeline_id: str) -> dict[str, Any]:
    """Execute a multi-stage pipeline.
    
    Args:
        pipeline_id: The ID of the pipeline to execute
        
    Returns:
        Dictionary with pipeline execution results
    """
    logger.info(f"Starting execution of pipeline {pipeline_id}")
    
    async def _execute() -> dict[str, Any]:
        async with get_db_context() as db:
            pipeline_repo = PipelineRepository(db)
            task_repo = TaskRepository(db)
            
            pipeline = await pipeline_repo.get_by_id(pipeline_id)
            if not pipeline:
                return {"status": "error", "message": "Pipeline not found"}
            
            await pipeline_repo.mark_running(pipeline_id)
            
            stages = pipeline.stages
            results: dict[str, Any] = {}
            completed_stages: set[str] = set()
            
            for i, stage in enumerate(stages):
                stage_name = stage.get("name", f"stage_{i}")
                task_id = stage.get("task_id")
                depends_on = stage.get("depends_on", [])
                
                if any(dep not in completed_stages for dep in depends_on):
                    error_msg = f"Dependencies not met for stage {stage_name}"
                    await pipeline_repo.mark_failed(pipeline_id, error_msg)
                    return {"status": "error", "message": error_msg}
                
                if task_id:
                    task = await task_repo.get_by_id(task_id)
                    if task and task.status.value == "pending":
                        execute_task.delay(task_id)
                        logger.info(f"Started task {task_id} for pipeline stage {stage_name}")
                    
                    for _ in range(600):
                        await asyncio.sleep(2)
                        task = await task_repo.get_by_id(task_id)
                        if task and task.status.value in ("completed", "failed", "cancelled", "timeout"):
                            if task.status.value == "completed":
                                completed_stages.add(stage_name)
                                results[stage_name] = {"status": "success", "task_id": task_id}
                            else:
                                error_msg = f"Stage {stage_name} failed"
                                await pipeline_repo.mark_failed(pipeline_id, error_msg)
                                return {"status": "error", "message": error_msg, "failed_stage": stage_name}
                            break
                    else:
                        error_msg = f"Stage {stage_name} timed out waiting for task"
                        await pipeline_repo.mark_failed(pipeline_id, error_msg)
                        return {"status": "error", "message": error_msg}
                else:
                    completed_stages.add(stage_name)
                    results[stage_name] = {"status": "skipped"}
            
            await pipeline_repo.mark_completed(pipeline_id)
            
            return {
                "status": "success",
                "pipeline_id": pipeline_id,
                "stages_completed": len(completed_stages),
                "results": results,
            }
    
    return asyncio.run(_execute())


@celery_app.task
def cleanup_old_results(days: int = 7) -> dict[str, int]:
    """Clean up old task results from storage.
    
    Args:
        days: Number of days to keep results
        
    Returns:
        Dictionary with cleanup statistics
    """
    async def _cleanup() -> dict[str, int]:
        async with get_db_context() as db:
            repo = TaskRepository(db)
            deleted = await repo.delete_old_completed(days)
        return {"tasks_deleted": deleted}
    
    return asyncio.run(_cleanup())


@celery_app.task
def sync_gpu_devices() -> dict[str, Any]:
    """Synchronize GPU device information from NVML.
    
    Returns:
        Dictionary with GPU device information
    """
    async def _sync() -> dict[str, Any]:
        from deepiri_zepgpu.core.gpu_manager import GPUManager
        
        gpu_manager = GPUManager()
        await gpu_manager.initialize()
        devices = gpu_manager.list_devices()
        
        async with get_db_context() as db:
            gpu_repo = GPURepository(db)
            
            for device in devices:
                await gpu_repo.update_or_create(
                    device_index=device.device_id,
                    name=device.name,
                    gpu_type=device.gpu_type.value,
                    total_memory_mb=device.total_memory_mb,
                    available_memory_mb=device.available_memory_mb,
                )
            
            return {
                "devices_synced": len(devices),
                "devices": [d.to_dict() for d in devices],
            }
    
    return asyncio.run(_sync())


@celery_app.task
def health_check() -> dict[str, Any]:
    """Perform system health check.
    
    Returns:
        Dictionary with health status
    """
    import psutil
    
    async def _check() -> dict[str, Any]:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        
        async with get_db_context() as db:
            task_repo = TaskRepository(db)
            gpu_repo = GPURepository(db)
            
            pending_count = await task_repo.count_by_status(
                db.models.Task.status if hasattr(db, 'models') else None
            )
            available_gpus = await gpu_repo.count_available()
            
            return {
                "status": "healthy",
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "available_gpus": available_gpus,
            }
    
    return asyncio.run(_check())


@celery_app.task
def update_gpu_metrics() -> dict[str, Any]:
    """Update GPU metrics from NVML.
    
    Returns:
        Dictionary with updated metrics
    """
    async def _update() -> dict[str, Any]:
        from deepiri_zepgpu.core.gpu_manager import GPUManager
        
        gpu_manager = GPUManager()
        await gpu_manager.initialize()
        
        await gpu_manager._update_gpu_metrics()
        
        async with get_db_context() as db:
            gpu_repo = GPURepository(db)
            
            updated = 0
            for device in gpu_manager.list_devices():
                await gpu_repo.update_metrics(
                    device_index=device.device_id,
                    utilization_percent=device.utilization_percent,
                    temperature_celsius=int(device.temperature_celsius),
                    power_draw_watts=device.power_draw_watts,
                    available_memory_mb=device.available_memory_mb,
                )
                updated += 1
            
            return {"devices_updated": updated}
    
    return asyncio.run(_update())


@celery_app.task(
    bind=True,
    base=GPUTask,
    soft_time_limit=3600,
    time_limit=3700,
)
def execute_scheduled_task(self, schedule_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Execute a scheduled task.
    
    Args:
        schedule_id: The ID of the scheduled task
        run_id: Optional existing run record ID
        
    Returns:
        Dictionary with execution results
    """
    logger.info(f"Executing scheduled task {schedule_id}")
    
    async def _execute() -> dict[str, Any]:
        async with get_db_context() as db:
            schedule_repo = ScheduleRepository(db)
            run_repo = ScheduleRunRepository(db)
            
            schedule = await schedule_repo.get_by_id(schedule_id)
            if not schedule:
                logger.warning(f"Schedule {schedule_id} not found")
                return {"status": "error", "message": "Schedule not found"}
            
            if not schedule.is_enabled:
                logger.info(f"Schedule {schedule_id} is disabled, skipping")
                return {"status": "skipped", "message": "Schedule is disabled"}
            
            scheduled_at = datetime.utcnow()
            
            run = None
            if run_id:
                run = await run_repo.get_by_id(run_id)
            else:
                run = await run_repo.create(
                    schedule_id=schedule_id,
                    user_id=schedule.user_id,
                    scheduled_at=scheduled_at,
                    status=ScheduleRunStatus.RUNNING,
                    trigger_type="scheduled",
                )
            
            if run:
                await run_repo.mark_running(run.id)
            
            try:
                task = DBTask(
                    id=str(uuid.uuid4()),
                    user_id=schedule.user_id,
                    name=f"[Scheduled] {schedule.name}",
                    func_name=schedule.func_name,
                    serialized_func=schedule.serialized_func,
                    args=schedule.args,
                    kwargs=schedule.kwargs,
                    priority=TaskPriority(schedule.priority),
                    gpu_memory_mb=schedule.gpu_memory_mb,
                    cpu_cores=schedule.cpu_cores,
                    timeout_seconds=schedule.timeout_seconds,
                    gpu_type=schedule.gpu_type,
                    allow_fallback_cpu=schedule.allow_fallback_cpu,
                    tags=schedule.tags,
                    metadata_json={**(schedule.metadata_json or {}), "schedule_id": schedule_id, "run_id": run.id if run else None},
                    callback_url=schedule.callback_url,
                    status=TaskStatus.PENDING,
                )
                db.add(task)
                await db.flush()
                
                if run:
                    run.task_id = task.id
                    await db.flush()
                
                execute_task.delay(task.id)
                
                await schedule_repo.record_run(schedule_id, task.id)
                next_run = await schedule_repo.calculate_next_run(schedule_id)
                
                if run:
                    await run_repo.mark_completed(
                        run.id,
                        result_summary={
                            "task_id": task.id,
                            "schedule_next_run": next_run.isoformat() if next_run else None,
                        },
                    )
                
                logger.info(f"Scheduled task {schedule_id} created task {task.id}")
                
                return {
                    "status": "success",
                    "schedule_id": schedule_id,
                    "task_id": task.id,
                    "run_id": run.id if run else None,
                    "next_run": next_run.isoformat() if next_run else None,
                }
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Scheduled task {schedule_id} failed: {e}")
                
                if run:
                    await run_repo.mark_failed(run.id, error_msg, traceback.format_exc())
                
                await schedule_repo.record_run(schedule_id, error=error_msg)
                return {"status": "error", "message": error_msg}
    
    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=GPUTask,
    soft_time_limit=3600,
    time_limit=3700,
)
def execute_delayed_task(self, task_id: str) -> dict[str, Any]:
    """Execute a task that was delayed (scheduled for a future time).
    
    Args:
        task_id: The ID of the task to execute
        
    Returns:
        Dictionary with execution results
    """
    logger.info(f"Executing delayed task {task_id}")
    
    async def _execute() -> dict[str, Any]:
        async with get_db_context() as db:
            repo = TaskRepository(db)
            
            task = await repo.get_by_id(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found")
                return {"status": "error", "message": "Task not found"}
            
            if task.status not in [TaskStatus.PENDING, TaskStatus.SCHEDULED]:
                logger.info(f"Task {task_id} is no longer pending (status: {task.status}), skipping")
                return {"status": "skipped", "message": f"Task status is {task.status}"}
            
            execute_task.delay(task_id)
            
            return {
                "status": "enqueued",
                "task_id": task_id,
            }
    
    return asyncio.run(_execute())


@celery_app.task
def sync_schedules_to_beat() -> dict[str, Any]:
    """Sync all enabled schedules to Celery Beat.
    
    This task should be run periodically to ensure beat schedule
    is in sync with the database.
    
    Returns:
        Dictionary with sync results
    """
    try:
        from deepiri_zepgpu.queue.beat_sync import beat_scheduler_sync
        
        synced = beat_scheduler_sync.sync_all_schedules()
        return {
            "status": "success",
            "schedules_synced": synced,
        }
    except Exception as e:
        logger.error(f"Failed to sync schedules: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


@celery_app.task
def cleanup_old_schedule_runs(days: int = 30) -> dict[str, int]:
    """Clean up old scheduled task run records.
    
    Args:
        days: Number of days to keep run records
        
    Returns:
        Dictionary with cleanup statistics
    """
    async def _cleanup() -> dict[str, int]:
        async with get_db_context() as db:
            repo = ScheduleRunRepository(db)
            deleted = await repo.delete_old_runs(days)
        return {"runs_deleted": deleted}
    
    return asyncio.run(_cleanup())


@celery_app.task(
    bind=True,
    base=GPUTask,
    soft_time_limit=7200,
    time_limit=7300,
)
def execute_gang_task(self, gang_task_id: str) -> dict[str, Any]:
    """Execute a gang scheduled task requiring multiple GPUs.
    
    Args:
        gang_task_id: The ID of the gang task to execute
        
    Returns:
        Dictionary with execution results
    """
    logger.info(f"Starting execution of gang task {gang_task_id}")
    
    async def _execute() -> dict[str, Any]:
        async with get_db_context() as db:
            from deepiri_zepgpu.database.repositories import GangScheduleRepository, GPURepository, FairShareRepository
            
            gang_repo = GangScheduleRepository(db)
            gpu_repo = GPURepository(db)
            fair_share_repo = FairShareRepository(db)
            
            gang_task = await gang_repo.get_by_id(gang_task_id)
            if not gang_task:
                logger.warning(f"Gang task {gang_task_id} not found")
                return {"status": "error", "message": "Gang task not found"}
            
            if gang_task.status != GangStatus.PENDING:
                logger.info(f"Gang task {gang_task_id} is no longer pending (status: {gang_task.status})")
                return {"status": "skipped", "message": f"Status is {gang_task.status}"}
            
            await gang_repo.update_status(gang_task_id, GangStatus.SCHEDULING)
            
            available_gpus = await gpu_repo.list_available_for_gang(
                num_gpus=gang_task.num_gpus_required,
                memory_per_gpu_mb=gang_task.gpu_memory_mb_per_gpu,
                gpu_type=gang_task.gpu_type,
            )
            
            if len(available_gpus) < gang_task.num_gpus_required:
                if gang_task.allow_partial_allocation and len(available_gpus) > 0:
                    gpu_ids = [g.device_index for g in available_gpus]
                else:
                    logger.info(f"Not enough GPUs available for gang task {gang_task_id}")
                    await gang_repo.update_status(gang_task_id, GangStatus.PENDING)
                    return {
                        "status": "waiting",
                        "message": "Not enough GPUs available",
                        "required": gang_task.num_gpus_required,
                        "available": len(available_gpus),
                    }
            else:
                gpu_ids = [g.device_index for g in available_gpus]
            
            allocated = await gpu_repo.allocate_gang(gpu_ids, gang_task_id)
            if not allocated:
                await gang_repo.update_status(gang_task_id, GangStatus.PENDING)
                return {"status": "error", "message": "Failed to allocate GPUs atomically"}
            
            await gang_repo.mark_allocated(gang_task_id, gpu_ids)
            
            try:
                import os
                os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in gpu_ids)
                
                result = None
                
                if gang_task.serialized_func:
                    func = cloudpickle.loads(gang_task.serialized_func)
                    func_args = cloudpickle.loads(gang_task.args) if gang_task.args else ()
                    func_kwargs = cloudpickle.loads(gang_task.kwargs) if gang_task.kwargs else {}
                    result = func(*func_args, **func_kwargs)
                elif gang_task.func_name:
                    module_name, func_name = gang_task.func_name.rsplit(".", 1)
                    import importlib
                    module = importlib.import_module(module_name)
                    func = getattr(module, func_name)
                    func_args = cloudpickle.loads(gang_task.args) if gang_task.args else ()
                    func_kwargs = cloudpickle.loads(gang_task.kwargs) if gang_task.kwargs else {}
                    result = func(*func_args, **func_kwargs)
                
                await gang_repo.mark_completed(gang_task_id)
                
                await gpu_repo.release_gang(gang_task_id)
                
                if gang_task.user_id:
                    execution_time_ms = 0
                    if gang_task.started_at:
                        execution_time_ms = int((datetime.utcnow() - gang_task.started_at).total_seconds() * 1000)
                    await fair_share_repo.record_gpu_usage(
                        gang_task.user_id,
                        gpu_seconds=execution_time_ms / 1000,
                        completed=True,
                    )
                
                logger.info(f"Gang task {gang_task_id} completed successfully")
                
                return {
                    "status": "success",
                    "gang_task_id": gang_task_id,
                    "gpu_ids": gpu_ids,
                    "result": result,
                }
                    
            except Exception as e:
                logger.error(f"Gang task {gang_task_id} failed: {e}")
                await gang_repo.mark_failed(gang_task_id, str(e), traceback.format_exc())
                await gpu_repo.release_gang(gang_task_id)
                
                if gang_task.user_id:
                    await fair_share_repo.record_gpu_usage(
                        gang_task.user_id,
                        gpu_seconds=0,
                        failed=True,
                    )
                
                raise
                
    return asyncio.run(_execute())


@celery_app.task(bind=True, base=GPUTask, soft_time_limit=300, time_limit=330)
def preempt_task(self, task_id: str, gang_task_id: str | None = None) -> dict[str, Any]:
    """Preempt a running task to make room for a higher priority task.
    
    Args:
        task_id: The ID of the task to preempt
        gang_task_id: Optional gang task ID that triggered the preemption
        
    Returns:
        Dictionary with preemption results
    """
    logger.info(f"Preempting task {task_id} for gang task {gang_task_id}")
    
    async def _execute() -> dict[str, Any]:
        async with get_db_context() as db:
            from deepiri_zepgpu.database.repositories import TaskRepository, PreemptionRepository, GPURepository
            
            task_repo = TaskRepository(db)
            preempt_repo = PreemptionRepository(db)
            gpu_repo = GPURepository(db)
            
            task = await task_repo.get_by_id(task_id)
            if not task:
                return {"status": "error", "message": "Task not found"}
            
            if task.status != TaskStatus.RUNNING:
                return {"status": "skipped", "message": f"Task is not running (status: {task.status})"}
            
            gpu_device_id = task.gpu_device_id
            
            execution_time_ms = 0
            if task.started_at:
                execution_time_ms = int((datetime.utcnow() - task.started_at).total_seconds() * 1000)
            
            checkpoint_ref = None
            if gang_task_id:
                preempt_record = await preempt_repo.create(
                    gang_task_id=gang_task_id,
                    preempted_task_id=task_id,
                    preempted_at=datetime.utcnow(),
                    reason="Higher priority gang task requires GPU",
                    execution_time_before_preemption_ms=execution_time_ms,
                    checkpoint_ref=checkpoint_ref,
                )
            
            await task_repo.mark_failed(task_id, "Task preempted by higher priority task", None)
            
            if gpu_device_id is not None:
                await gpu_repo.release(gpu_device_id)
            
            logger.info(f"Task {task_id} preempted successfully")
            
            return {
                "status": "success",
                "preempted_task_id": task_id,
                "gang_task_id": gang_task_id,
                "execution_time_ms": execution_time_ms,
            }
    
    return asyncio.run(_execute())


@celery_app.task
def check_and_preempt() -> dict[str, Any]:
    """Check for pending high-priority tasks and preempt if needed.
    
    This task runs periodically to handle priority inversion by preempting
    lower priority tasks when higher priority gang tasks are waiting.
    
    Returns:
        Dictionary with preemption results
    """
    logger.info("Checking for preemption opportunities")
    
    async def _check() -> dict[str, Any]:
        async with get_db_context() as db:
            from deepiri_zepgpu.database.repositories import GangScheduleRepository, TaskRepository, GPURepository
            
            gang_repo = GangScheduleRepository(db)
            task_repo = TaskRepository(db)
            gpu_repo = GPURepository(db)
            
            pending_gangs = await gang_repo.list_pending(limit=10)
            
            preempted = 0
            for gang in pending_gangs:
                if gang.priority < 4:
                    continue
                
                available_count = await gpu_repo.count_available_for_gang(gang.num_gpus_required)
                
                if available_count == 0:
                    preemptible = await gpu_repo.list_preemptible(min_priority=gang.priority - 1)
                    
                    if len(preemptible) >= gang.num_gpus_required:
                        for gpu in preemptible[:gang.num_gpus_required]:
                            if gpu.current_task_id:
                                preempt_task.delay(gpu.current_task_id, gang.id)
                                preempted += 1
                                break
                        
                        if preempted >= gang.num_gpus_required:
                            break
            
            return {
                "status": "success",
                "preempted_count": preempted,
                "pending_gangs_checked": len(pending_gangs),
            }
    
    return asyncio.run(_check())


@celery_app.task
def update_fair_share_usage() -> dict[str, Any]:
    """Update GPU usage tracking for fair share scheduling.
    
    Returns:
        Dictionary with update results
    """
    async def _update() -> dict[str, Any]:
        async with get_db_context() as db:
            from deepiri_zepgpu.database.repositories import TaskRepository, FairShareRepository
            
            task_repo = TaskRepository(db)
            fair_share_repo = FairShareRepository(db)
            
            completed_tasks = await task_repo.list_by_status(TaskStatus.COMPLETED, limit=100)
            
            for task in completed_tasks:
                if task.user_id and task.execution_time_ms:
                    await fair_share_repo.record_gpu_usage(
                        task.user_id,
                        gpu_seconds=task.execution_time_ms / 1000,
                        completed=True,
                    )
            
            return {
                "status": "success",
                "tasks_processed": len(completed_tasks),
            }
    
    return asyncio.run(_update())


@celery_app.task
def get_fair_share_weights() -> dict[str, Any]:
    """Get fair share weights for all active users.
    
    Returns:
        Dictionary with user weights
    """
    async def _get() -> dict[str, Any]:
        async with get_db_context() as db:
            from deepiri_zepgpu.database.repositories import FairShareRepository
            
            fair_share_repo = FairShareRepository(db)
            buckets = await fair_share_repo.list_all()
            
            weights = {}
            for bucket in buckets:
                if bucket.user_id:
                    weight = await fair_share_repo.get_scheduling_weight(bucket.user_id)
                    weights[str(bucket.user_id)] = {
                        "weight": weight,
                        "gpu_seconds_used": bucket.gpu_seconds_used,
                        "gpu_seconds_limit": bucket.gpu_seconds_limit,
                        "is_over_limit": bucket.is_over_limit,
                    }
            
            return {
                "status": "success",
                "weights": weights,
            }
    
    return asyncio.run(_get())


@celery_app.task
def reset_expired_fair_share_periods() -> dict[str, int]:
    """Reset fair share counters for users whose period has expired.
    
    Returns:
        Dictionary with reset statistics
    """
    async def _reset() -> dict[str, int]:
        async with get_db_context() as db:
            from deepiri_zepgpu.database.repositories import FairShareRepository
            
            fair_share_repo = FairShareRepository(db)
            buckets = await fair_share_repo.list_all()
            
            reset_count = 0
            for bucket in buckets:
                if fair_share_repo._is_period_expired(bucket):
                    bucket.gpu_seconds_used = 0
                    bucket.tasks_completed = 0
                    bucket.tasks_failed = 0
                    bucket.tasks_preempted = 0
                    bucket.period_start = datetime.utcnow()
                    reset_count += 1
            
            if reset_count > 0:
                await db.flush()
            
            return {"buckets_reset": reset_count}
    
    return asyncio.run(_reset())
