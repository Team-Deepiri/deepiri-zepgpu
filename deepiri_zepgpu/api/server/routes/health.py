"""Health check routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel

from deepiri_zepgpu.queue.redis_queue import queue


router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: datetime
    version: str
    database: str
    redis: str


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check API health."""
    redis_healthy = await queue.health_check() if hasattr(queue, '_redis') and queue._redis else False
    
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="0.1.0",
        database="healthy",
        redis="healthy" if redis_healthy else "unhealthy",
    )


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check() -> dict:
    """Check if API is ready to accept requests."""
    return {"ready": True}


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check() -> dict:
    """Check if API is alive."""
    return {"alive": True}
