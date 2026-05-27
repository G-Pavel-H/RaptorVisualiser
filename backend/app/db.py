"""MongoDB Atlas integration via Motor.

Two collections:
- builds: { _id, status, text_preview, tree_json, created_at, owner_session_id, ip }
- usage:  { _id, ip, date, count }   (composite index on ip+date)

Trees auto-expire 24h after creation via a TTL index on `created_at`.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .settings import get_settings

TTL_SECONDS = 24 * 60 * 60
DAILY_BUILD_LIMIT = 50000


@lru_cache
def get_db() -> Optional[AsyncIOMotorDatabase]:
    settings = get_settings()
    if not settings.mongodb_uri:
        return None
    client = AsyncIOMotorClient(settings.mongodb_uri)
    return client[settings.mongodb_db]


async def ensure_indexes() -> None:
    db = get_db()
    if db is None:
        return
    await db.builds.create_index("created_at", expireAfterSeconds=TTL_SECONDS)
    await db.usage.create_index([("ip", 1), ("date", 1)], unique=True)


def _today() -> str:
    return dt.date.today().isoformat()


async def check_and_increment_quota(ip: str) -> Dict[str, int]:
    """Atomically increment today's count for `ip`.

    Returns {used, remaining}. Raises QuotaExceeded if over limit.
    """
    db = get_db()
    if db is None:
        # No DB configured — skip rate limiting (local dev).
        return {"used": 0, "remaining": DAILY_BUILD_LIMIT}

    doc = await db.usage.find_one_and_update(
        {"ip": ip, "date": _today()},
        {"$inc": {"count": 1}},
        upsert=True,
        return_document=True,
    )
    used = doc["count"]
    if used > DAILY_BUILD_LIMIT:
        # Roll back the increment so the user can retry tomorrow.
        await db.usage.update_one(
            {"ip": ip, "date": _today()}, {"$inc": {"count": -1}}
        )
        raise QuotaExceeded(used=DAILY_BUILD_LIMIT, remaining=0)
    return {"used": used, "remaining": DAILY_BUILD_LIMIT - used}


async def save_build(
    build_id: str,
    *,
    text: str,
    status: str,
    tree_json: Optional[Dict[str, Any]],
    ip: str,
    owner_session_id: Optional[str] = None,
) -> None:
    db = get_db()
    if db is None:
        return
    await db.builds.update_one(
        {"_id": build_id},
        {
            "$set": {
                "status": status,
                "text_preview": text[:300],
                "tree_json": tree_json,
                "ip": ip,
                "owner_session_id": owner_session_id,
            },
            "$setOnInsert": {"created_at": dt.datetime.utcnow()},
        },
        upsert=True,
    )


async def load_build(build_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    if db is None:
        return None
    return await db.builds.find_one({"_id": build_id})


class QuotaExceeded(Exception):
    def __init__(self, *, used: int, remaining: int) -> None:
        super().__init__(f"daily build limit reached ({used}/{used})")
        self.used = used
        self.remaining = remaining
