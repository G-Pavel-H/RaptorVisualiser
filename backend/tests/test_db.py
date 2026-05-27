"""Quota tests use a fake AsyncIOMotorDatabase — no Mongo connection needed."""
from unittest.mock import patch

import pytest

from app import db


class FakeCollection:
    def __init__(self) -> None:
        self.docs = {}

    async def find_one_and_update(self, filt, update, upsert=False, return_document=True):
        key = (filt["ip"], filt["date"])
        doc = self.docs.get(key, {"ip": filt["ip"], "date": filt["date"], "count": 0})
        doc["count"] += update["$inc"]["count"]
        self.docs[key] = doc
        return dict(doc)

    async def update_one(self, filt, update):
        key = (filt["ip"], filt["date"])
        if key in self.docs:
            self.docs[key]["count"] += update["$inc"]["count"]


class FakeDb:
    def __init__(self) -> None:
        self.usage = FakeCollection()
        self.builds = FakeCollection()


@pytest.mark.asyncio
async def test_quota_allows_up_to_limit():
    fake = FakeDb()
    with patch.object(db, "get_db", return_value=fake):
        for i in range(db.DAILY_BUILD_LIMIT):
            r = await db.check_and_increment_quota("1.2.3.4")
            assert r["used"] == i + 1
            assert r["remaining"] == db.DAILY_BUILD_LIMIT - (i + 1)


@pytest.mark.asyncio
async def test_quota_blocks_after_limit():
    fake = FakeDb()
    with patch.object(db, "get_db", return_value=fake):
        for _ in range(db.DAILY_BUILD_LIMIT):
            await db.check_and_increment_quota("1.2.3.4")
        with pytest.raises(db.QuotaExceeded):
            await db.check_and_increment_quota("1.2.3.4")
        # Rollback worked: counter is still at the limit, not above.
        doc = fake.usage.docs[("1.2.3.4", db._today())]
        assert doc["count"] == db.DAILY_BUILD_LIMIT


@pytest.mark.asyncio
async def test_quota_when_no_db_configured_is_unlimited():
    with patch.object(db, "get_db", return_value=None):
        r = await db.check_and_increment_quota("1.2.3.4")
        assert r["remaining"] == db.DAILY_BUILD_LIMIT
