"""Celery app for distributed task queue."""

from __future__ import annotations

import os

from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
beat_schedule_db = os.getenv("CELERY_BEAT_SCHEDULE_DB", "redis://localhost:6379/3")

celery_app = Celery(
    "deepiri_zepgpu",
    broker=broker_url,
    backend=result_backend,
    include=["deepiri_zepgpu.queue.tasks"],
)

celery_app.conf.update(
    # Broker messages cross a network trust boundary. Celery's JSON serializer
    # supports the primitive task IDs/results used here without permitting
    # arbitrary object construction during message decoding.
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=86400,
    task_routes={
        "deepiri_zepgpu.queue.tasks.execute_task": {"queue": "gpu_tasks"},
        "deepiri_zepgpu.queue.tasks.execute_pipeline": {"queue": "pipelines"},
        "deepiri_zepgpu.queue.tasks.execute_scheduled_task": {"queue": "schedules"},
        "deepiri_zepgpu.queue.tasks.execute_delayed_task": {"queue": "schedules"},
        "deepiri_zepgpu.queue.tasks.execute_gang_task": {"queue": "gang"},
        "deepiri_zepgpu.queue.tasks.preempt_task": {"queue": "preemption"},
        "deepiri_zepgpu.queue.tasks.check_and_preempt": {"queue": "preemption"},
        "deepiri_zepgpu.queue.tasks.sweep_node_assignment_timeouts": {"queue": "schedules"},
    },
    task_annotations={
        "deepiri_zepgpu.queue.tasks.execute_task": {
            "rate_limit": "100/m",
        },
    },
    beat_scheduler="celery.beat:PersistentScheduler",
    beat_schedule_filename="/tmp/celerybeat-schedule",
    beat_schedule_db=beat_schedule_db,
    beat_sync_every=1,
    beat_schedule={
        "sweep-node-assignment-timeouts": {
            "task": "deepiri_zepgpu.queue.tasks.sweep_node_assignment_timeouts",
            "schedule": 30.0,
        },
    },
    redis_socket_timeout=5,
    redis_connection_retry=True,
    redis_connection_retry_delay=10,
)

if __name__ == "__main__":
    celery_app.start()
