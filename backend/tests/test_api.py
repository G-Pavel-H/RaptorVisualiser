"""API surface tests. Builds are stubbed so no OpenAI calls happen."""
import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import cost_tracker, events
from app.build_session import BuildSession
from app.main import app

client = TestClient(app)


async def _no_cap(_ip: str) -> None:
    return None


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
    with patch.object(cost_tracker, "assert_under_cap", _no_cap), \
         patch.object(BuildSession, "run", _fake_run):
        resp = client.post("/api/builds", json={"text": "hello world"})
    assert resp.status_code == 200
    assert "build_id" in resp.json()


def test_create_build_rejects_oversized_input():
    big = "a" * 20_001
    resp = client.post("/api/builds", json={"text": big})
    assert resp.status_code == 413
    assert resp.json()["detail"]["kind"] == "too_large"


def test_create_build_rejects_empty():
    resp = client.post("/api/builds", json={"text": ""})
    assert resp.status_code == 422


def test_create_build_refuses_when_mongo_down():
    # Default settings have no MONGODB_URI → cap guard raises mongo_down.
    resp = client.post("/api/builds", json={"text": "hello world"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["kind"] == "mongo_down"


def test_create_build_returns_429_on_site_cap():
    async def _site_cap(_ip: str) -> None:
        raise cost_tracker.CapExceeded(
            reason="site_cap", used_usd=0.95, cap_usd=1.0, resets_at="2026-05-31T00:00:00Z"
        )

    with patch.object(cost_tracker, "assert_under_cap", _site_cap):
        resp = client.post("/api/builds", json={"text": "x" * 100})
    assert resp.status_code == 429
    assert resp.json()["detail"]["kind"] == "site_cap"


def test_create_build_returns_429_on_ip_cap():
    async def _ip_cap(_ip: str) -> None:
        raise cost_tracker.CapExceeded(
            reason="ip_cap", used_usd=0.095, cap_usd=0.1, resets_at="2026-05-31T00:00:00Z"
        )

    with patch.object(cost_tracker, "assert_under_cap", _ip_cap):
        resp = client.post("/api/builds", json={"text": "x" * 100})
    assert resp.status_code == 429
    assert resp.json()["detail"]["kind"] == "ip_cap"


def test_get_build_unknown_id_404():
    resp = client.get("/api/builds/does-not-exist")
    assert resp.status_code == 404


def test_get_build_after_stub_run_returns_tree():
    with patch.object(cost_tracker, "assert_under_cap", _no_cap), \
         patch.object(BuildSession, "run", _fake_run):
        build_id = client.post("/api/builds", json={"text": "hi"}).json()["build_id"]
        import time

        for _ in range(20):
            r = client.get(f"/api/builds/{build_id}")
            if r.json()["status"] == "done":
                break
            time.sleep(0.05)
    assert r.json()["status"] == "done"
    assert r.json()["tree"]["nodes"] == []


def test_query_rejects_if_build_not_ready():
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
