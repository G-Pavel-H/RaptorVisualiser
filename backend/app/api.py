"""HTTP + SSE surface for builds."""
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import cost_tracker, db, events
from .build_session import BuildSession, OUT_OF_FUNDS_COPY, registry
from .settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class CreateBuildBody(BaseModel):
    text: str = Field(..., min_length=1)


class QueryBody(BaseModel):
    query: str = Field(..., min_length=1)
    method: str = Field("collapsed_tree", pattern="^(collapsed_tree|tree_traversal)$")


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For if Render/Vercel is fronting us, else the socket.
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if fwd:
        return fwd
    return request.client.host if request.client else "unknown"


def _cap_exceeded_response(exc: cost_tracker.CapExceeded) -> HTTPException:
    if exc.reason == "mongo_down":
        return HTTPException(
            status_code=503,
            detail={
                "kind": "mongo_down",
                "message": "Spend tracker offline — service temporarily unavailable.",
            },
        )
    if exc.reason == "site_cap":
        return HTTPException(
            status_code=429,
            detail={
                "kind": "site_cap",
                "message": "Daily site-wide AI budget reached. Please come back tomorrow.",
                "used_usd": round(exc.used_usd, 4),
                "cap_usd": exc.cap_usd,
                "resets_at": exc.resets_at,
            },
        )
    return HTTPException(
        status_code=429,
        detail={
            "kind": "ip_cap",
            "message": "You've hit your personal daily limit. The cap resets at midnight UTC.",
            "used_usd": round(exc.used_usd, 4),
            "cap_usd": exc.cap_usd,
            "resets_at": exc.resets_at,
        },
    )


@router.post("/builds")
async def create_build(body: CreateBuildBody, request: Request) -> Dict[str, Any]:
    settings = get_settings()
    if len(body.text) > settings.max_input_chars:
        raise HTTPException(
            status_code=413,
            detail={
                "kind": "too_large",
                "message": f"Input exceeds {settings.max_input_chars:,} characters.",
            },
        )

    ip = _client_ip(request)
    try:
        await cost_tracker.assert_under_cap(ip)
    except cost_tracker.CapExceeded as exc:
        raise _cap_exceeded_response(exc) from exc

    session = registry.create(body.text, ip=ip)
    await db.save_build(
        session.id, text=body.text, status="pending", tree_json=None, ip=ip
    )

    async def run_and_persist() -> None:
        await session.run()
        await db.save_build(
            session.id,
            text=body.text,
            status=session.status,
            tree_json=session.tree_json,
            ip=ip,
        )

    asyncio.create_task(run_and_persist())
    return {"build_id": session.id}


@router.get("/builds/{build_id}")
async def get_build(build_id: str) -> Dict[str, Any]:
    session = registry.get(build_id)
    if session is not None:
        return {
            "build_id": session.id,
            "status": session.status,
            "tree": session.tree_json,
            "error": session.error,
            "error_kind": session.error_kind,
        }
    doc = await db.load_build(build_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Build not found.")
    return {
        "build_id": build_id,
        "status": doc.get("status"),
        "tree": doc.get("tree_json"),
        "error": None,
        "error_kind": None,
    }


@router.get("/builds/{build_id}/stream")
async def stream_build(build_id: str, request: Request) -> EventSourceResponse:
    session = _require(build_id)

    async def gen() -> AsyncIterator[Dict[str, str]]:
        while True:
            if await request.is_disconnected():
                return
            event = await session.queue.get()
            yield {
                "event": event.stage,
                "data": json.dumps(event.to_dict()),
            }
            if event.stage in ("done", "error"):
                return

    return EventSourceResponse(gen(), ping=15)


@router.post("/builds/{build_id}/query")
async def query_build(build_id: str, body: QueryBody, request: Request) -> Dict[str, Any]:
    session = _require(build_id)
    # Allow query against a partially-built tree (out-of-funds mid-build leaves
    # a usable structure). Only refuse when there's literally no tree to walk.
    if session.tree is None:
        raise HTTPException(status_code=409, detail="Build not ready.")

    ip = _client_ip(request)
    try:
        await cost_tracker.assert_under_cap(ip)
    except cost_tracker.CapExceeded as exc:
        raise _cap_exceeded_response(exc) from exc

    from raptor import TreeRetriever
    from raptor.tree_retriever import TreeRetrieverConfig

    collapse = body.method == "collapsed_tree"
    # The session's embedding model is the same instance the build used, so
    # the retriever embeds the query under the same key the nodes used.
    retriever_kwargs: Dict[str, Any] = {}
    if session.embedding_model is not None:
        retriever_kwargs["embedding_model"] = session.embedding_model
        retriever_kwargs["context_embedding_model"] = session.embedding_key
    retriever = TreeRetriever(TreeRetrieverConfig(**retriever_kwargs), session.tree)
    try:
        context, layer_info = await asyncio.to_thread(
            retriever.retrieve,
            body.query,
            None,
            None,
            10,
            3500,
            collapse,
            True,
        )
    except Exception as exc:
        if cost_tracker.is_insufficient_quota_error(exc):
            raise HTTPException(
                status_code=503,
                detail={"kind": "out_of_funds", "message": OUT_OF_FUNDS_COPY},
            ) from exc
        raise
    retrieved_ids = sorted({entry["node_index"] for entry in (layer_info or [])})
    return {
        "method": body.method,
        "context": context,
        "retrieved_node_ids": retrieved_ids,
        "layer_information": layer_info,
    }


def _require(build_id: str) -> BuildSession:
    session = registry.get(build_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Build not found.")
    return session
