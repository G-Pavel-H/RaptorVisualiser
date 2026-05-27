"""HTTP + SSE surface for builds."""
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import db, events
from .build_session import BuildSession, registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

MAX_INPUT_CHARS = 40_000


class CreateBuildBody(BaseModel):
    text: str = Field(..., min_length=1)


class QueryBody(BaseModel):
    query: str = Field(..., min_length=1)
    method: str = Field("collapsed_tree", pattern="^(collapsed_tree|tree_traversal)$")


@router.post("/builds")
async def create_build(body: CreateBuildBody, request: Request) -> Dict[str, Any]:
    if len(body.text) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Input exceeds {MAX_INPUT_CHARS} characters.",
        )

    ip = request.client.host if request.client else "unknown"
    try:
        quota = await db.check_and_increment_quota(ip)
    except db.QuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={"message": "Daily build limit reached.", "remaining": 0},
        ) from exc

    session = registry.create(body.text)
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
    return {"build_id": session.id, "quota": quota}


@router.get("/builds/{build_id}")
async def get_build(build_id: str) -> Dict[str, Any]:
    session = registry.get(build_id)
    if session is not None:
        return {
            "build_id": session.id,
            "status": session.status,
            "tree": session.tree_json,
            "error": session.error,
        }
    doc = await db.load_build(build_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Build not found.")
    return {
        "build_id": build_id,
        "status": doc.get("status"),
        "tree": doc.get("tree_json"),
        "error": None,
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

    # sse-starlette emits its own comment-style keep-alive every `ping` seconds.
    return EventSourceResponse(gen(), ping=15)


@router.post("/builds/{build_id}/query")
async def query_build(build_id: str, body: QueryBody) -> Dict[str, Any]:
    session = _require(build_id)
    if session.status != "done" or session.tree is None:
        raise HTTPException(status_code=409, detail="Build not complete.")

    from raptor import TreeRetriever

    collapse = body.method == "collapsed_tree"
    retriever = TreeRetriever(session_retriever_config(session), session.tree)
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
    retrieved_ids = sorted({entry["node_index"] for entry in (layer_info or [])})
    return {
        "method": body.method,
        "context": context,
        "retrieved_node_ids": retrieved_ids,
        "layer_information": layer_info,
    }


def session_retriever_config(session: BuildSession):
    from raptor.tree_retriever import TreeRetrieverConfig

    return TreeRetrieverConfig()


def _require(build_id: str) -> BuildSession:
    session = registry.get(build_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Build not found.")
    return session
