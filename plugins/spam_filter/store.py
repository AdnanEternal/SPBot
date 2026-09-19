from typing import Any

from core.database_manager import DatabaseManager
from core.ttl_cache import TTLCache


DEFAULT_FLOOD_COUNT = 5
DEFAULT_FLOOD_SECONDS = 10
DEFAULT_MAX_LINKS = 3
DEFAULT_MAX_REPEAT = 3


class SpamSettingsStore:
    """
    تنظیمات فیلتر اسپم هر گروه.

    برای پیام‌های عادی، تنظیمات از RAM خوانده می‌شوند
    تا SQLite در مسیر اصلی spam detection نباشد.

    Cache:
    - حداکثر 512 گروه
    - TTL = 15 دقیقه
    """

    TABLE = "spam_settings"

    CACHE_MAX_GROUPS = 512
    CACHE_TTL_SECONDS = 900

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

        self._cache = TTLCache[
            int,
            dict[str, Any],
        ](
            max_entries=self.CACHE_MAX_GROUPS,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "flood_count": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_FLOOD_COUNT}"
                ),
                "flood_seconds": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_FLOOD_SECONDS}"
                ),
                "max_links": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_MAX_LINKS}"
                ),
                "max_repeat": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_MAX_REPEAT}"
                ),
            },
        )

    async def _ensure_row(
        self,
        group_id: int,
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
            },
            or_ignore=True,
        )

    async def get(
        self,
        group_id: int,
    ) -> dict[str, Any]:
        # مسیر سریع
        cached = self._cache.get(group_id)

        if cached is not None:
            return dict(cached)

        # فقط cache miss
        await self._ensure_row(group_id)

        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        settings = dict(row)

        self._cache.set(
            group_id,
            settings,
        )

        return dict(settings)

    async def set_flood(
        self,
        group_id: int,
        count: int,
        seconds: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "flood_count": count,
                "flood_seconds": seconds,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(group_id)

        if cached is not None:
            cached["flood_count"] = count
            cached["flood_seconds"] = seconds

            self._cache.set(
                group_id,
                cached,
            )

    async def set_max_links(
        self,
        group_id: int,
        count: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "max_links": count,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(group_id)

        if cached is not None:
            cached["max_links"] = count

            self._cache.set(
                group_id,
                cached,
            )

    async def set_max_repeat(
        self,
        group_id: int,
        count: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "max_repeat": count,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(group_id)

        if cached is not None:
            cached["max_repeat"] = count

            self._cache.set(
                group_id,
                cached,
            )