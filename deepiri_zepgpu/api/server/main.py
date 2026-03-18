"""FastAPI main application."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from deepiri_zepgpu.api.server.routes import api_router
from deepiri_zepgpu.api.server.routes import websocket
from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database import init_db, close_db
from deepiri_zepgpu.queue.redis_queue import queue
from deepiri_zepgpu.storage.result_store import result_store


REQUEST_COUNT = Counter(
    "zepgpu_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "zepgpu_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)

ACTIVE_TASKS = Gauge(
    "zepgpu_active_tasks",
    "Number of active tasks",
)

GPU_UTILIZATION = Gauge(
    "zepgpu_gpu_utilization",
    "GPU utilization percentage",
    ["device_index"],
)

GPU_MEMORY_USED = Gauge(
    "zepgpu_gpu_memory_used_mb",
    "GPU memory used in MB",
    ["device_index"],
)

QUEUE_LENGTH = Gauge(
    "zepgpu_task_queue_length",
    "Number of pending tasks in queue",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    await init_db()
    await queue.connect()
    result_store.initialize()
    yield
    await close_db()
    await queue.disconnect()


app = FastAPI(
    title=settings.api.title,
    description=settings.api.description,
    version=settings.api.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware to collect metrics."""
    start_time = time.time()
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    
    endpoint = request.url.path
    if endpoint.startswith("/api/v1"):
        endpoint = "/api/v1" + endpoint.split("/")[2] if len(endpoint.split("/")) > 2 else "/api/v1"
    else:
        endpoint = endpoint
    
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status=response.status_code,
    ).inc()
    
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=endpoint,
    ).observe(duration)
    
    return response


app.include_router(api_router, prefix="/api/v1")
app.include_router(websocket.router, prefix="/api/v1", tags=["WebSocket"])


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint."""
    return {
        "name": settings.api.title,
        "version": settings.api.version,
        "status": "running",
    }


@app.get("/metrics", tags=["Monitoring"])
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/api/v1/stats", tags=["System"])
async def get_stats():
    """Get system statistics."""
    import psutil
    from deepiri_zepgpu.database.session import get_db_context
    from deepiri_zepgpu.database.repositories import TaskRepository, GPURepository
    from deepiri_zepgpu.database.models.task import TaskStatus
    
    async with get_db_context() as db:
        task_repo = TaskRepository(db)
        gpu_repo = GPURepository(db)
        
        stats = {
            "queue": {
                "pending_tasks": await task_repo.count_by_status(TaskStatus.PENDING),
                "running_tasks": await task_repo.count_by_status(TaskStatus.RUNNING),
                "completed_tasks": await task_repo.count_by_status(TaskStatus.COMPLETED),
                "failed_tasks": await task_repo.count_by_status(TaskStatus.FAILED),
            },
            "gpus": {
                "available": await gpu_repo.count_available(),
                "total_memory_gb": (await gpu_repo.get_total_memory_mb()) / 1024,
            },
            "websocket": {
                "connections": manager.get_connection_count(),
                "users": manager.get_user_count(),
            },
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
            },
        }
    
    return stats


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__,
        },
    )


def create_app() -> FastAPI:
    """Create FastAPI application."""
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "deepiri_zepgpu.api.server.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        workers=1 if settings.api.reload else settings.api.workers,
    )
