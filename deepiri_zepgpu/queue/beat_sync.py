"""Celery Beat scheduler synchronization service."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import redis
from croniter import croniter

from deepiri_zepgpu.config import settings

logger = logging.getLogger(__name__)


class BeatSchedulerSync:
    """Manages Celery Beat schedule synchronization from database to Redis."""

    def __init__(self):
        self.redis_client = redis.from_url(
            settings.schedule.beat_schedule_db,
            decode_responses=True,
        )
        self.schedule_key = "celery:beat:schedules"
        self.lock_key = "celery:beat:sync:lock"
        self.lock_timeout = 60

    def _acquire_lock(self) -> bool:
        """Acquire a distributed lock for sync operation."""
        return bool(self.redis_client.set(self.lock_key, "1", nx=True, ex=self.lock_timeout))

    def _release_lock(self) -> None:
        """Release the distributed lock."""
        self.redis_client.delete(self.lock_key)

    def get_beat_schedule(self) -> dict[str, dict[str, Any]]:
        """Get the current beat schedule from Redis."""
        data = self.redis_client.hgetall(self.schedule_key)
        schedule = {}
        for key, value in data.items():
            try:
                schedule[key] = json.loads(value)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse schedule entry: {key}")
        return schedule

    def sync_schedule(
        self,
        schedule_id: str,
        task_name: str,
        args: tuple = (),
        kwargs: dict | None = None,
        schedule_type: str = "cron",
        cron_expr: str | None = None,
        interval_seconds: int | None = None,
        run_at: datetime | None = None,
    ) -> None:
        """Sync a single schedule to Redis."""
        if kwargs is None:
            kwargs = {}

        entry = {
            "task": task_name,
            "args": args,
            "kwargs": kwargs,
            "schedule_type": schedule_type,
            "last_updated": datetime.utcnow().isoformat(),
        }

        if schedule_type == "cron" and cron_expr:
            entry["cron"] = cron_expr
            next_run = self._get_next_cron_run(cron_expr)
            entry["next_run"] = next_run.isoformat() if next_run else None
        elif schedule_type == "interval" and interval_seconds:
            entry["interval_seconds"] = interval_seconds
            entry["next_run"] = (datetime.utcnow() + timedelta(seconds=interval_seconds)).isoformat()
        elif schedule_type == "once" and run_at:
            entry["run_at"] = run_at.isoformat()
            entry["next_run"] = run_at.isoformat()

        self.redis_client.hset(self.schedule_key, schedule_id, json.dumps(entry))
        logger.debug(f"Synced schedule {schedule_id} to beat")

    def remove_schedule(self, schedule_id: str) -> None:
        """Remove a schedule from Redis."""
        self.redis_client.hdel(self.schedule_key, schedule_id)
        logger.debug(f"Removed schedule {schedule_id} from beat")

    def _get_next_cron_run(self, cron_expr: str, from_time: datetime | None = None) -> datetime | None:
        """Get the next run time for a cron expression."""
        try:
            if from_time is None:
                from_time = datetime.utcnow()
            cron = croniter(cron_expr, from_time)
            return cron.get_next(datetime)
        except ValueError:
            logger.warning(f"Invalid cron expression: {cron_expr}")
            return None

    def sync_all_schedules(self) -> int:
        """Sync all enabled schedules from database to Redis beat.
        
        Returns:
            Number of schedules synced.
        """
        if not self._acquire_lock():
            logger.debug("Sync already in progress, skipping")
            return 0

        try:
            from deepiri_zepgpu.database.session import get_db_context
            from deepiri_zepgpu.database.repositories import ScheduleRepository
            from deepiri_zepgpu.database.models.scheduled_task import ScheduleType, ScheduleStatus

            synced = 0
            schedules_to_remove = set(self.get_beat_schedule().keys())

            async def _sync():
                async with get_db_context() as db:
                    repo = ScheduleRepository(db)
                    schedules = await repo.get_enabled_schedules()

                    for schedule in schedules:
                        schedules_to_remove.discard(schedule.id)

                        if schedule.schedule_type == ScheduleType.CRON and schedule.cron_expression:
                            self.sync_schedule(
                                schedule_id=schedule.id,
                                task_name="deepiri_zepgpu.queue.tasks.execute_scheduled_task",
                                args=(schedule.id,),
                                schedule_type="cron",
                                cron_expr=schedule.cron_expression,
                            )
                        elif schedule.schedule_type == ScheduleType.INTERVAL and schedule.interval_seconds:
                            self.sync_schedule(
                                schedule_id=schedule.id,
                                task_name="deepiri_zepgpu.queue.tasks.execute_scheduled_task",
                                args=(schedule.id,),
                                schedule_type="interval",
                                interval_seconds=schedule.interval_seconds,
                            )
                        elif schedule.schedule_type == ScheduleType.ONCE and schedule.start_datetime:
                            self.sync_schedule(
                                schedule_id=schedule.id,
                                task_name="deepiri_zepgpu.queue.tasks.execute_scheduled_task",
                                args=(schedule.id,),
                                schedule_type="once",
                                run_at=schedule.start_datetime,
                            )

                        synced += 1

                    return synced

            synced = asyncio_run(_sync())

            for schedule_id in schedules_to_remove:
                self.remove_schedule(schedule_id)

            logger.info(f"Synced {synced} schedules to Celery Beat")
            return synced

        except Exception as e:
            logger.error(f"Failed to sync schedules: {e}")
            return 0
        finally:
            self._release_lock()


def asyncio_run(coro):
    """Run an async coroutine from sync code."""
    import asyncio
    return asyncio.run(coro)


beat_scheduler_sync = BeatSchedulerSync()
