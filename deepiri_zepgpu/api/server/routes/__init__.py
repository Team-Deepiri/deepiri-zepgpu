"""FastAPI server routes initialization."""

from fastapi import APIRouter

from deepiri_zepgpu.api.server.routes import tasks, users, pipelines, gpu, health, websocket, schedules, gang_scheduling, namespaces, cloud

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(pipelines.router, prefix="/pipelines", tags=["Pipelines"])
api_router.include_router(schedules.router, prefix="/schedules", tags=["Schedules"])
api_router.include_router(gang_scheduling.router, prefix="/gang", tags=["Gang Scheduling"])
api_router.include_router(namespaces.router, prefix="/namespaces", tags=["Namespaces"])
api_router.include_router(cloud.router, prefix="/cloud", tags=["Cloud"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(users.router, prefix="/auth", tags=["Auth"])
api_router.include_router(gpu.router, prefix="/gpu", tags=["GPU"])
api_router.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])

__all__ = ["api_router"]
