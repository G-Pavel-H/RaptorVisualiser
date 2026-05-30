"""Smoke tests for db helpers — no real Mongo required."""
from unittest.mock import patch

import pytest

from app import db


@pytest.mark.asyncio
async def test_save_build_is_a_noop_without_db():
    """get_db() returning None must short-circuit cleanly."""
    with patch.object(db, "get_db", return_value=None):
        await db.save_build("id-1", text="hi", status="done", tree_json=None, ip="1.2.3.4")


@pytest.mark.asyncio
async def test_load_build_returns_none_without_db():
    with patch.object(db, "get_db", return_value=None):
        assert await db.load_build("anything") is None
