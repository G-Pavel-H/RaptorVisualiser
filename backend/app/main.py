import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import cost_tracker

logger = logging.getLogger(__name__)
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

    # `Exception` handlers run inside starlette's ServerErrorMiddleware which
    # sits OUTSIDE our CORSMiddleware — so responses from it don't get CORS
    # headers automatically. Add them by hand or the browser will blame CORS
    # for every server error.
    allowed_origin = settings.frontend_origin

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        origin = request.headers.get("origin")
        headers: dict[str, str] = {}
        if origin and (allowed_origin == "*" or origin == allowed_origin):
            headers["access-control-allow-origin"] = origin
            headers["access-control-allow-credentials"] = "true"
            headers["vary"] = "Origin"
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "kind": "generic",
                    "message": "Internal server error.",
                    "error": exc.__class__.__name__,
                }
            },
            headers=headers,
        )

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

    # ---------- Angular static hosting ----------
    # The frontend build (`ng build`) produces `frontend/dist/raptor-visualizer/browser/`.
    # If that directory exists (i.e. we're running in production after the
    # combined build), serve it as the site root. /api/* routes still win
    # because they're registered above and StaticFiles only handles unmatched
    # paths.
    frontend_dist = (
        Path(__file__).resolve().parent.parent.parent
        / "frontend" / "dist" / "raptor-visualizer" / "browser"
    )
    if frontend_dist.is_dir():
        # Mount static assets at /.  `html=True` makes it serve index.html
        # for the root request automatically.
        app.mount(
            "/static-assets",
            StaticFiles(directory=frontend_dist),
            name="static-assets",
        )

        index_file = frontend_dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            """Serve a real file if it exists, else fall back to index.html
            so Angular's client-side routing can handle deep links."""
            # /api/* should have been handled by the router already; if we
            # got here for /api/* it's a genuine 404.
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found.")
            candidate = frontend_dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)
    else:
        # Backend running solo (local dev without `ng build`). Give a friendly
        # JSON at / instead of FastAPI's default 404.
        @app.get("/")
        def root() -> dict:
            return {
                "service": "raptor-live-api",
                "status": "ok",
                "note": "frontend not built — run `ng build` to bundle UI here",
            }

    return app


app = create_app()
