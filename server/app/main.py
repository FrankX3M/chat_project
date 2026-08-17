import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.logging import configure_logging
from app.core.redis_client import get_redis
from app.ws.event_handlers import matchmaking_loop
from app.ws.router import router as ws_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = get_redis()
    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(matchmaking_loop(redis, stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await loop_task
        await redis.aclose()


app = FastAPI(
    title="Anon Chat API",
    description="Анонимный чат — единый REST + WebSocket контракт для web и mobile клиентов.",
    version="0.1.0",
    lifespan=lifespan,
)

# MVP: разрешаем любой origin для локальной разработки. В проде — сузить до
# конкретных origin'ов клиентов (см. README "Готовность к переезду на VPS").
# allow_credentials=False осознанно: авторизация тут через Bearer-токен в
# заголовке, а не через cookie, так что credentials (cookies/Authorization
# через браузерный fetch с credentials:'include') не нужны — а сочетание
# allow_origins=["*"] + allow_credentials=True само по себе анти-паттерн
# (см. код-ревью: CORS misconfiguration).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
