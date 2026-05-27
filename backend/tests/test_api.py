"""API surface tests. Builds are stubbed so no OpenAI calls happen."""
import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import events
from app.build_session import BuildSession
from app.main import app

client = TestClient(app)


async def _fake_run(self: BuildSession) -> None:
    """Replacement for BuildSession.run that emits 2 events then 'done'."""
    self._loop = asyncio.get_running_loop()
    self.status = "running"
    self.emit_threadsafe(events.chunked(["one", "two"]))
    self.emit_threadsafe(events.embedded(0, "one"))
    self.tree_json = {"num_layers": 0, "nodes": [], "edges": [], "root_ids": [], "leaf_ids": []}
    self.status = "done"
    self.emit_threadsafe(events.done(self.tree_json))


def test_create_build_returns_id():
    with patch.object(BuildSession, "run", _fake_run):
        resp = client.post("/api/builds", json={"text": "hello world"})
    assert resp.status_code == 200
    assert "build_id" in resp.json()


def test_create_build_rejects_oversized_input():
    big = "a" * 40_001
    resp = client.post("/api/builds", json={"text": big})
    assert resp.status_code == 413


def test_create_build_rejects_empty():
    resp = client.post("/api/builds", json={"text": ""})
    assert resp.status_code == 422


def test_get_build_unknown_id_404():
    resp = client.get("/api/builds/does-not-exist")
    assert resp.status_code == 404


def test_get_build_after_stub_run_returns_tree():
    with patch.object(BuildSession, "run", _fake_run):
        build_id = client.post("/api/builds", json={"text": "hi"}).json()["build_id"]
        # Give the background task a moment.
        import time

        for _ in range(20):
            r = client.get(f"/api/builds/{build_id}")
            if r.json()["status"] == "done":
                break
            time.sleep(0.05)
    assert r.json()["status"] == "done"
    assert r.json()["tree"]["nodes"] == []


def test_query_rejects_if_build_not_done():
    with patch.object(BuildSession, "run", _fake_run):
        # Create but query before background task finishes — use registry directly
        from app.build_session import registry

        session = registry.create("never run")
        resp = client.post(
            f"/api/builds/{session.id}/query",
            json={"query": "what?", "method": "collapsed_tree"},
        )
    assert resp.status_code == 409


def test_query_rejects_bad_method():
    resp = client.post(
        "/api/builds/anything/query",
        json={"query": "q", "method": "bogus"},
    )
    assert resp.status_code == 422
