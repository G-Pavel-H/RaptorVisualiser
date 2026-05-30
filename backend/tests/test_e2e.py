"""End-to-end tests against the FastAPI surface.

No OpenAI key / RAPTOR build is exercised — `BuildSession.run` and
`TreeRetriever` are stubbed so the tests run hermetically. The goal is to
guard the *contract* between routes, session, cost tracker and CORS layer,
so regressions like the recent "query 500 → CORS misreport" or the
"`context_embedding_model='OpenAI'` mismatch" cannot ship silently.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from raptor.EmbeddingModels import BaseEmbeddingModel

from app import cost_tracker, events
from app.build_session import BuildSession, registry
from app.main import app

client = TestClient(app)


class FakeEmbeddingModel(BaseEmbeddingModel):
    """Tiny real-subclass so TreeRetrieverConfig's isinstance check passes."""

    def create_embedding(self, text):
        return [0.0, 0.0]


# ---------- helpers ----------


async def _no_cap(_ip: str) -> None:
    return None


def _fake_tree() -> Any:
    """Bare-minimum stand-in for a RAPTOR Tree object that the API needs."""

    class FakeNode:
        def __init__(self, idx: int) -> None:
            self.index = idx
            self.text = f"node {idx}"
            self.children: set = set()
            self.embeddings = {"EMB": [0.0, 0.0]}

    leaves = {0: FakeNode(0)}
    return type(
        "FakeTree",
        (),
        {
            "all_nodes": leaves,
            "root_nodes": leaves,
            "leaf_nodes": leaves,
            "num_layers": 0,
            "layer_to_nodes": {0: list(leaves.values())},
        },
    )()


def _stub_completed_session(status: str = "done") -> BuildSession:
    """Drop a fully-built session straight into the registry."""
    session = registry.create("paste text here", ip="1.2.3.4")
    session.status = status
    session.tree_json = {
        "num_layers": 0,
        "nodes": [{"id": 0, "layer": 0, "text": "x", "children": []}],
        "edges": [],
        "root_ids": [0],
        "leaf_ids": [0],
    }
    session._tree = _fake_tree()  # type: ignore[attr-defined]
    session._embedding_model = FakeEmbeddingModel()  # type: ignore[attr-defined]
    session._embedding_key = "EMB"  # type: ignore[attr-defined]
    return session


async def _fake_run(self: BuildSession) -> None:
    self._loop = asyncio.get_running_loop()
    self.status = "running"
    self.emit_threadsafe(events.chunked(["alpha", "beta"]))
    self.emit_threadsafe(events.embedded(0, "alpha"))
    self.emit_threadsafe(events.embedded(1, "beta"))
    self.emit_threadsafe(events.layer_complete(0, 2))
    self.tree_json = {
        "num_layers": 0,
        "nodes": [
            {"id": 0, "layer": 0, "text": "alpha", "children": []},
            {"id": 1, "layer": 0, "text": "beta", "children": []},
        ],
        "edges": [],
        "root_ids": [0, 1],
        "leaf_ids": [0, 1],
    }
    self._tree = _fake_tree()  # so query mode works
    self._embedding_model = FakeEmbeddingModel()
    self._embedding_key = "EMB"
    self.status = "done"
    self.emit_threadsafe(events.done(self.tree_json))


def _wait_done(build_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        r = client.get(f"/api/builds/{build_id}")
        last = r.json()
        if last.get("status") == "done":
            return last
        time.sleep(0.02)
    return last


# ---------- happy path: build → done → query → retrieved ----------


def test_build_to_query_full_flow():
    with patch.object(cost_tracker, "assert_under_cap", _no_cap), \
         patch.object(BuildSession, "run", _fake_run), \
         patch("raptor.TreeRetriever") as Retriever:
        retr = MagicMock()
        retr.retrieve.return_value = (
            "assembled context here",
            [{"node_index": 0, "layer_number": 0}, {"node_index": 1, "layer_number": 0}],
        )
        Retriever.return_value = retr

        # 1. Build
        create = client.post("/api/builds", json={"text": "x" * 100})
        assert create.status_code == 200
        build_id = create.json()["build_id"]

        # 2. Wait for done
        done = _wait_done(build_id)
        assert done["status"] == "done"
        assert done["tree"]["nodes"][0]["id"] == 0

        # 3. Query
        q = client.post(
            f"/api/builds/{build_id}/query",
            json={"query": "what is alpha?", "method": "collapsed_tree"},
        )
        assert q.status_code == 200
        body = q.json()
        assert body["context"] == "assembled context here"
        assert body["retrieved_node_ids"] == [0, 1]
        assert body["method"] == "collapsed_tree"


# ---------- regression: TreeRetrieverConfig must use session's embedding key ----------


def test_query_passes_session_embedding_model_to_retriever():
    """Regression: TreeRetrieverConfig defaults context_embedding_model='OpenAI'.
    Our custom embedding model stores under 'EMB' — passing the default
    causes a 500 when retrieval calls get_embeddings(nodes, 'OpenAI').
    """
    session = _stub_completed_session()

    with patch.object(cost_tracker, "assert_under_cap", _no_cap), \
         patch("raptor.TreeRetriever") as Retriever, \
         patch("raptor.tree_retriever.TreeRetrieverConfig") as Config:
        Retriever.return_value.retrieve.return_value = ("ctx", [])
        Config.return_value = MagicMock()

        r = client.post(
            f"/api/builds/{session.id}/query",
            json={"query": "q", "method": "collapsed_tree"},
        )
        assert r.status_code == 200, r.text

        kwargs = Config.call_args.kwargs
        assert kwargs.get("context_embedding_model") == "EMB"
        assert kwargs.get("embedding_model") is session.embedding_model


# ---------- 500 responses must still have CORS headers ----------


def test_unhandled_500_carries_cors_headers():
    """If a handler raises, the response must go through CORS middleware so
    the browser shows the real error instead of blaming CORS."""

    async def _boom(_ip: str):
        raise RuntimeError("kaboom")

    # TestClient re-raises server exceptions by default for debug visibility;
    # disable that so we exercise the real production code path through the
    # exception handler + CORS middleware.
    safe_client = TestClient(app, raise_server_exceptions=False)
    with patch.object(cost_tracker, "assert_under_cap", _boom):
        r = safe_client.post(
            "/api/builds",
            json={"text": "x" * 100},
            headers={"Origin": "http://localhost:4200"},
        )

    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "http://localhost:4200"
    body = r.json()
    assert body["detail"]["kind"] == "generic"


# ---------- cap variants ----------


def test_query_blocked_by_site_cap():
    session = _stub_completed_session()

    async def _site_cap(_ip: str) -> None:
        raise cost_tracker.CapExceeded(
            reason="site_cap", used_usd=0.95, cap_usd=1.0,
            resets_at="2026-05-31T00:00:00Z",
        )

    with patch.object(cost_tracker, "assert_under_cap", _site_cap):
        r = client.post(
            f"/api/builds/{session.id}/query",
            json={"query": "q", "method": "collapsed_tree"},
        )
    assert r.status_code == 429
    assert r.json()["detail"]["kind"] == "site_cap"


def test_query_blocked_by_ip_cap():
    session = _stub_completed_session()

    async def _ip_cap(_ip: str) -> None:
        raise cost_tracker.CapExceeded(
            reason="ip_cap", used_usd=0.095, cap_usd=0.1,
            resets_at="2026-05-31T00:00:00Z",
        )

    with patch.object(cost_tracker, "assert_under_cap", _ip_cap):
        r = client.post(
            f"/api/builds/{session.id}/query",
            json={"query": "q", "method": "collapsed_tree"},
        )
    assert r.status_code == 429
    assert r.json()["detail"]["kind"] == "ip_cap"


def test_create_build_uses_xforwarded_for_when_present():
    """Behind Render/Vercel the client IP is in the proxy header."""
    captured: dict = {}

    async def _cap(ip: str) -> None:
        captured["ip"] = ip

    with patch.object(cost_tracker, "assert_under_cap", _cap), \
         patch.object(BuildSession, "run", _fake_run):
        client.post(
            "/api/builds",
            json={"text": "x" * 100},
            headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"},
        )

    assert captured["ip"] == "203.0.113.5"


# ---------- out-of-funds during query ----------


def test_query_translates_insufficient_quota_to_503():
    session = _stub_completed_session()

    class FakeOpenAIErr(Exception):
        pass

    err = FakeOpenAIErr("nope")
    err.code = "insufficient_quota"  # type: ignore[attr-defined]

    with patch.object(cost_tracker, "assert_under_cap", _no_cap), \
         patch("raptor.TreeRetriever") as Retriever:
        retr = MagicMock()
        retr.retrieve.side_effect = err
        Retriever.return_value = retr

        r = client.post(
            f"/api/builds/{session.id}/query",
            json={"query": "q", "method": "collapsed_tree"},
        )
    assert r.status_code == 503
    assert r.json()["detail"]["kind"] == "out_of_funds"


# ---------- validation guards ----------


def test_build_rejects_oversized_input_with_kind():
    r = client.post("/api/builds", json={"text": "x" * 20_001})
    assert r.status_code == 413
    assert r.json()["detail"]["kind"] == "too_large"


def test_query_unknown_build_404():
    r = client.post(
        "/api/builds/does-not-exist/query",
        json={"query": "?", "method": "collapsed_tree"},
    )
    assert r.status_code == 404


def test_build_method_validation():
    r = client.post(
        "/api/builds/anything/query",
        json={"query": "q", "method": "bogus_method"},
    )
    assert r.status_code == 422
