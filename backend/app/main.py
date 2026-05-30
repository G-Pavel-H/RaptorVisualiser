import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import asyncio

from . import cost_tracker
from .api import router as api_router
from .db import ensure_indexes
from .settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    # RAPTOR's OpenAI() client reads OPENAI_API_KEY from os.environ, not from
    # our Settings object. Push it across so the build worker can authenticate.
    if settings.openai_api_key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    app = FastAPI(title="RAPTOR Live Visualizer", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.on_event("startup")
    async def _startup() -> None:
        # Capture the running loop so worker threads can schedule async DB
        # writes (used by cost_tracker.record_usage_threadsafe).
        cost_tracker.bind_loop(asyncio.get_running_loop())
        try:
            await ensure_indexes()
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning("Mongo init skipped: %s", exc)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "openai_key_configured": bool(settings.openai_api_key),
        }

    return app


app = create_app()
