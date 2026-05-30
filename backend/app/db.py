"""MongoDB Atlas integration via Motor.

Collections:
- builds          {_id, status, text_preview, tree_json, created_at, ip}
- spend_log       {_id: 'YYYY-MM-DD', cost_usd, prompt_tokens, completion_tokens, updated_at}
- spend_log_ip    {_id: 'YYYY-MM-DD::<ip>', date, ip, cost_usd, prompt_tokens, completion_tokens}

`builds` expires after 24h via TTL. Spend logs expire after 30 days so we can
glance at recent traffic without growing unbounded.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .settings import get_settings

TTL_BUILDS_SECONDS = 24 * 60 * 60
TTL_SPEND_SECONDS = 30 * 24 * 60 * 60


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
    await db.builds.create_index("created_at", expireAfterSeconds=TTL_BUILDS_SECONDS)
    await db.spend_log.create_index("updated_at", expireAfterSeconds=TTL_SPEND_SECONDS)
    await db.spend_log_ip.create_index("updated_at", expireAfterSeconds=TTL_SPEND_SECONDS)
    await db.spend_log_ip.create_index([("date", 1), ("ip", 1)])


async def save_build(
    build_id: str,
    *,
    text: str,
    status: str,
    tree_json: Optional[Dict[str, Any]],
    ip: str,
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
            },
            "$setOnInsert": {"created_at": dt.datetime.now(dt.timezone.utc)},
        },
        upsert=True,
    )


async def load_build(build_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    if db is None:
        return None
    return await db.builds.find_one({"_id": build_id})
