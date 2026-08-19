from fastapi import APIRouter

from app.api.v1 import auth, config, rooms, search, settings, stats

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(search.router)
api_router.include_router(rooms.router)
api_router.include_router(stats.router)
api_router.include_router(config.router)
