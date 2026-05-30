"""Process-wide OpenAI spend tracking + global / per-IP cap enforcement.

Design notes
------------
* The cap is checked *before* a request and recorded *after*. With multiple
  in-flight requests at the threshold there's a small overshoot window —
  hence the SAFETY_MARGIN (default 0.9) so the refusal point is well below
  the real ceiling.
* The semaphore is a `threading.Semaphore`, not `asyncio.Semaphore`, because
  RAPTOR runs in a worker thread (via `asyncio.to_thread`). Embeddings,
  summarizations and QA calls all share one ceiling.
* If Mongo is unreachable we refuse all work (return CapExceeded("mongo_down"))
  rather than silently letting spend run free.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

from .db import get_db
from .settings import get_settings

logger = logging.getLogger(__name__)


# USD per 1M tokens, (input, output). Update when OpenAI publishes new prices.
# Embeddings only return total_tokens — we charge the input column for them.
PRICE_TABLE: dict[str, Tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "text-embedding-3-small": (0.02, 0.02),
    "text-embedding-3-large": (0.13, 0.13),
    "text-embedding-ada-002": (0.10, 0.10),
}
# Conservative fallback for an unknown model — picks the most expensive
# row so we err on the side of refusing too early rather than too late.
_FALLBACK_PRICE = (0.60, 2.40)


# ----- semaphore -----------------------------------------------------------

_settings = get_settings()
_concurrency = threading.BoundedSemaphore(_settings.openai_max_concurrency)


def acquire_slot() -> None:
    _concurrency.acquire()


def release_slot() -> None:
    try:
        _concurrency.release()
    except ValueError:
        pass  # over-release guard


# ----- cost math -----------------------------------------------------------

def cost_for(model: str, in_tokens: int, out_tokens: int) -> float:
    in_per_m, out_per_m = PRICE_TABLE.get(model, _FALLBACK_PRICE)
    return (in_tokens * in_per_m + out_tokens * out_per_m) / 1_000_000


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def _resets_at() -> str:
    tomorrow = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)
    return dt.datetime.combine(tomorrow, dt.time.min, tzinfo=dt.timezone.utc).isoformat()


# ----- recording -----------------------------------------------------------

async def record_usage(model: str, in_tokens: int, out_tokens: int, ip: str) -> None:
    """Atomically increment today's global + per-IP spend counters."""
    db = get_db()
    if db is None:
        return  # No Mongo: caps disabled, see assert_under_cap for the refusal.
    cost = cost_for(model, in_tokens, out_tokens)
    today = _today()
    try:
        await db.spend_log.update_one(
            {"_id": today},
            {
                "$inc": {
                    "cost_usd": cost,
                    "prompt_tokens": in_tokens,
                    "completion_tokens": out_tokens,
                },
                "$set": {"updated_at": dt.datetime.now(dt.timezone.utc)},
            },
            upsert=True,
        )
        await db.spend_log_ip.update_one(
            {"_id": f"{today}::{ip}"},
            {
                "$inc": {
                    "cost_usd": cost,
                    "prompt_tokens": in_tokens,
                    "completion_tokens": out_tokens,
                },
                "$set": {
                    "updated_at": dt.datetime.now(dt.timezone.utc),
                    "date": today,
                    "ip": ip,
                },
            },
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to record OpenAI spend; tracker may drift.")


def record_usage_threadsafe(model: str, in_tokens: int, out_tokens: int, ip: str) -> None:
    """Schedule `record_usage` from a worker thread onto the main loop."""
    loop = _main_loop
    if loop is None:
        return
    asyncio.run_coroutine_threadsafe(record_usage(model, in_tokens, out_tokens, ip), loop)


# Captured at app startup so worker threads can schedule async DB writes.
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


# ----- cap guard -----------------------------------------------------------

@dataclass
class CapExceeded(Exception):
    reason: str               # 'site_cap' | 'ip_cap' | 'mongo_down'
    used_usd: float
    cap_usd: float
    resets_at: str

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.reason} ({self.used_usd:.4f}/{self.cap_usd:.4f})"


async def assert_under_cap(ip: str) -> None:
    """Raise CapExceeded if today's global *or* per-IP spend would refuse work.

    Refusal threshold is `safety_margin * cap` so we never get within 10 % of
    the real ceiling.
    """
    s = get_settings()
    db = get_db()
    if db is None:
        # Mongo is the source of truth — refuse rather than let spend drift.
        raise CapExceeded(
            reason="mongo_down",
            used_usd=0.0,
            cap_usd=s.daily_usd_cap,
            resets_at=_resets_at(),
        )

    today = _today()
    global_doc = await db.spend_log.find_one({"_id": today})
    global_used = float((global_doc or {}).get("cost_usd", 0.0))
    if global_used >= s.daily_usd_cap * s.safety_margin:
        raise CapExceeded(
            reason="site_cap",
            used_usd=global_used,
            cap_usd=s.daily_usd_cap,
            resets_at=_resets_at(),
        )

    ip_doc = await db.spend_log_ip.find_one({"_id": f"{today}::{ip}"})
    ip_used = float((ip_doc or {}).get("cost_usd", 0.0))
    if ip_used >= s.per_ip_usd_cap * s.safety_margin:
        raise CapExceeded(
            reason="ip_cap",
            used_usd=ip_used,
            cap_usd=s.per_ip_usd_cap,
            resets_at=_resets_at(),
        )


def is_insufficient_quota_error(exc: BaseException) -> bool:
    """OpenAI uses HTTP 429 for both rate-limits and 'no money on the account'.
    The `code` discriminates."""
    code = getattr(exc, "code", None) or ""
    body = getattr(exc, "body", None) or {}
    if isinstance(body, dict):
        code = code or body.get("code", "") or (body.get("error") or {}).get("code", "")
    return code == "insufficient_quota"
