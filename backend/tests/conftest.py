"""Shared test fixtures.

`backend/.env` exists in dev and points at a real MongoDB Atlas cluster. We
*never* want unit tests to talk to that — both for safety and because a
motor client bound to one asyncio loop blows up the moment the next test
creates a fresh loop. So we hard-force `get_db()` to return None for every
test, and individual tests opt in to a fake DB via `unittest.mock.patch`.
"""
import pytest

from app import cost_tracker, db


@pytest.fixture(autouse=True)
def _no_real_mongo(monkeypatch):
    monkeypatch.setattr(db, "get_db", lambda: None)
    monkeypatch.setattr(cost_tracker, "get_db", lambda: None)
    yield
