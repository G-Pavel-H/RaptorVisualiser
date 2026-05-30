"""Unit tests for cost_tracker: pricing math, cap guard, semaphore."""
import threading
import time
from unittest.mock import AsyncMock, patch

import pytest

from app import cost_tracker
from app.settings import get_settings


def test_cost_for_known_model():
    # gpt-4o-mini: $0.15 / $0.60 per 1M tokens (input / output)
    # 1000 in + 500 out  →  (1000*0.15 + 500*0.60) / 1e6 = 0.00045
    cost = cost_tracker.cost_for("gpt-4o-mini", 1000, 500)
    assert cost == pytest.approx(0.00045, rel=1e-6)


def test_cost_for_embedding_charges_input_only():
    # text-embedding-3-small: $0.02 / $0.02 per 1M
    cost = cost_tracker.cost_for("text-embedding-3-small", 10_000, 0)
    assert cost == pytest.approx(0.0002, rel=1e-6)


def test_cost_for_unknown_model_uses_fallback():
    cost = cost_tracker.cost_for("totally-made-up-model", 1_000_000, 1_000_000)
    # Fallback is the most expensive row, so any real model should be cheaper.
    cheapest = cost_tracker.cost_for("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost > cheapest


class FakeCollection:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, filt):
        return self.doc


class FakeDb:
    def __init__(self, global_used=0.0, ip_used=0.0):
        self.spend_log = FakeCollection({"cost_usd": global_used} if global_used else None)
        self.spend_log_ip = FakeCollection({"cost_usd": ip_used} if ip_used else None)


@pytest.mark.asyncio
async def test_assert_under_cap_passes_when_well_below():
    with patch.object(cost_tracker, "get_db", return_value=FakeDb(0.05, 0.005)):
        await cost_tracker.assert_under_cap("1.2.3.4")  # no raise


@pytest.mark.asyncio
async def test_assert_under_cap_trips_site_cap_at_90pct_margin():
    settings = get_settings()
    # 90% of $1.0 = $0.90, so $0.91 should trip.
    over = settings.daily_usd_cap * settings.safety_margin + 0.01
    with patch.object(cost_tracker, "get_db", return_value=FakeDb(over, 0.0)):
        with pytest.raises(cost_tracker.CapExceeded) as excinfo:
            await cost_tracker.assert_under_cap("1.2.3.4")
        assert excinfo.value.reason == "site_cap"


@pytest.mark.asyncio
async def test_assert_under_cap_trips_ip_cap_at_90pct_margin():
    settings = get_settings()
    over = settings.per_ip_usd_cap * settings.safety_margin + 0.001
    with patch.object(cost_tracker, "get_db", return_value=FakeDb(0.0, over)):
        with pytest.raises(cost_tracker.CapExceeded) as excinfo:
            await cost_tracker.assert_under_cap("1.2.3.4")
        assert excinfo.value.reason == "ip_cap"


@pytest.mark.asyncio
async def test_assert_under_cap_returns_mongo_down_when_no_db():
    with patch.object(cost_tracker, "get_db", return_value=None):
        with pytest.raises(cost_tracker.CapExceeded) as excinfo:
            await cost_tracker.assert_under_cap("1.2.3.4")
        assert excinfo.value.reason == "mongo_down"


def test_semaphore_holds_at_configured_concurrency():
    # The module-level semaphore is sized by openai_max_concurrency=8.
    inflight = 0
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal inflight, peak
        cost_tracker.acquire_slot()
        try:
            with lock:
                inflight += 1
                peak = max(peak, inflight)
            time.sleep(0.05)
        finally:
            with lock:
                inflight -= 1
            cost_tracker.release_slot()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak <= get_settings().openai_max_concurrency


def test_is_insufficient_quota_error_detects_openai_code():
    class FakeErr(Exception):
        pass

    e = FakeErr("nope")
    e.code = "insufficient_quota"
    assert cost_tracker.is_insufficient_quota_error(e)

    e2 = FakeErr("rate")
    e2.code = "rate_limit_exceeded"
    assert not cost_tracker.is_insufficient_quota_error(e2)


def test_is_insufficient_quota_error_reads_body():
    class FakeErr(Exception):
        pass

    e = FakeErr("nope")
    e.body = {"error": {"code": "insufficient_quota"}}
    assert cost_tracker.is_insufficient_quota_error(e)
