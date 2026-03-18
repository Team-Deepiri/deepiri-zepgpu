"""Celery app for distributed task queue."""

from __future__ import annotations

import os
from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "deepiri_zepgpu",
    broker=broker_url,
    backend=result_backend,
    include=["deepiri_zepgpu.queue.tasks"],
)

celery_app.conf.update(
    task_serializer="pickle",
    accept_content=["pickle", "json"],
    result_serializer="pickle",
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
    },
    task_annotations={
        "deepiri_zepgpu.queue.tasks.execute_task": {
            "rate_limit": "100/m",
        },
    },
)

if __name__ == "__main__":
    celery_app.start()
