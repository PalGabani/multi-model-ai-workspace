import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api import auth, conversations, usage
from app.api import models as model_api
from app.core.config import settings
from app.core.database import SessionFactory, engine
from app.models import ModelConfiguration, ModelProvider

logger = logging.getLogger("modelspace")


async def initialize_database() -> None:
    async with SessionFactory() as session:
        for definition in settings.model_catalog():
            api_key, base_url = settings.provider_credentials(definition.provider)
            provider = await session.get(ModelProvider, definition.provider)
            if provider is None:
                provider = ModelProvider(
                    id=definition.provider,
                    display_name=definition.provider.replace("-", " ").title(),
                    base_url=base_url,
                    is_enabled=True,
                )
                session.add(provider)
            else:
                provider.base_url = base_url
            model = await session.get(ModelConfiguration, definition.id)
            if model is None:
                model = ModelConfiguration(
                    id=definition.id,
                    provider_id=definition.provider,
                    label=definition.label,
                    description=definition.description,
                    input_cost_per_million=definition.input_cost_per_million,
                    output_cost_per_million=definition.output_cost_per_million,
                    context_window=definition.context_window,
                    is_enabled=definition.enabled,
                )
                session.add(model)
            else:
                model.provider_id = definition.provider
                model.label = definition.label
                model.description = definition.description
                model.input_cost_per_million = definition.input_cost_per_million
                model.output_cost_per_million = definition.output_cost_per_million
                model.context_window = definition.context_window
                model.is_enabled = definition.enabled
            if not api_key:
                logger.info(
                    "Provider %s has no API key configured; its models will be shown as unavailable.",
                    definition.provider,
                )
        await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await initialize_database()
    redis_client = (
        Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
    )
    if redis_client:
        try:
            await redis_client.ping()
        except RedisError:
            logger.exception("Redis is configured but unavailable; API rate limiting is disabled.")
            await redis_client.aclose()
            redis_client = None
    app.state.redis = redis_client
    yield
    if redis_client:
        await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="Modelspace API",
    description="A multi-model AI workspace API with tenant isolation and SSE responses.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def auth_rate_limit(request, call_next):
    if request.method == "POST" and request.url.path in {"/api/auth/login", "/api/auth/register"}:
        redis_client = getattr(app.state, "redis", None)
        if redis_client:
            client_host = request.client.host if request.client else "unknown"
            window = int(time.time() // 60)
            try:
                count = await redis_client.incr(f"auth-limit:{client_host}:{window}")
                if count == 1:
                    await redis_client.expire(f"auth-limit:{client_host}:{window}", 65)
                if count > 12:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many sign-in attempts. Try again in a minute."},
                    )
            except RedisError:
                logger.exception("Redis rate-limit check failed.")
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Authentication is temporarily unavailable."},
                )
    return await call_next(request)


app.include_router(auth.router)
app.include_router(model_api.router)
app.include_router(conversations.router)
app.include_router(usage.router)


@app.get("/api/health", tags=["operations"])
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "modelspace-api"}
