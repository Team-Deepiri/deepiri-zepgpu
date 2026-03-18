"""Celery tasks for distributed GPU task execution."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime
from typing import Any

import cloudpickle
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from deepiri_zepgpu.database.session import get_db_context
from deepiri_zepgpu.database.repositories import TaskRepository, PipelineRepository, GPURepository, AuditRepository
from deepiri_zepgpu.database.models.audit_log import AuditAction
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
