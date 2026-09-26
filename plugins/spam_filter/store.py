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
        cached = self._cache.get(group_id)

        if cached is not None:
            return dict(cached)

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


class SpamWhitelistStore:
    """
    کاربرانی که Spam Filter باید کاملاً نادیده‌شان بگیرد.

    whitelist فقط مربوط به Spam Filter است و روی
    content_filter / violation_manager تأثیری ندارد.

    برای مسیر عادی تشخیص اسپم، اطلاعات از RAM خوانده می‌شوند
    و SQLite فقط هنگام cache miss یا تغییر whitelist استفاده می‌شود.
    """

    TABLE = "spam_whitelist"

    CACHE_MAX_GROUPS = 512
    CACHE_TTL_SECONDS = 900

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

        self._cache = TTLCache[
            int,
            set[int],
        ](
            max_entries=self.CACHE_MAX_GROUPS,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                ),
                "group_id": (
                    "INTEGER NOT NULL"
                ),
                "user_id": (
                    "INTEGER NOT NULL"
                ),
            },
            indexes=[
                "group_id",
                "user_id",
            ],
        )

    async def _load_group(
        self,
        group_id: int,
    ) -> set[int]:
        cached = self._cache.get(group_id)

        if cached is not None:
            return set(cached)

        rows = await self.db.select_all(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        users = {
            int(row["user_id"])
            for row in rows
        }

        self._cache.set(
            group_id,
            users,
        )

        return set(users)

    async def is_exempt(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        users = await self._load_group(group_id)
        return user_id in users

    async def add(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        users = await self._load_group(group_id)

        if user_id in users:
            return False

        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
            },
        )

        users.add(user_id)

        self._cache.set(
            group_id,
            users,
        )

        return True

    async def remove(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        users = await self._load_group(group_id)

        if user_id not in users:
            return False

        await self.db.execute(
            f"""
            DELETE FROM {self.TABLE}
            WHERE group_id = ?
              AND user_id = ?
            """,
            (
                group_id,
                user_id,
            ),
        )

        users.discard(user_id)

        self._cache.set(
            group_id,
            users,
        )

        return True

    async def get_all(
        self,
        group_id: int,
    ) -> list[int]:
        users = await self._load_group(group_id)
        return sorted(users)



class SpamContextStore:
    """
    اطلاعات persistent مربوط به حضور کاربران در گروه.

    فعلاً فقط زمان آخرین ورود کاربر را نگه می‌دارد.
    """

    TABLE = "spam_user_context"

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                ),
                "group_id": (
                    "INTEGER NOT NULL"
                ),
                "user_id": (
                    "INTEGER NOT NULL"
                ),
                "joined_at": (
                    "REAL NOT NULL"
                ),
            },
            unique=[
                (
                    "group_id",
                    "user_id",
                )
            ],
            indexes=[
                "group_id",
                "user_id",
            ],
        )

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

    async def set_joined_at(
        self,
        group_id: int,
        user_id: int,
        joined_at: float,
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
                "joined_at": joined_at,
            },
            or_ignore=True,
        )

        await self.db.update(
            self.TABLE,
            {
                "joined_at": joined_at,
            },
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
        )

    async def get_joined_at(
        self,
        group_id: int,
        user_id: int,
    ) -> float | None:
        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
        )

        if not row:
            return None

        return float(
            row["joined_at"]
        )

    async def clear_user(
        self,
        group_id: int,
        user_id: int,
    ) -> None:
        await self.db.delete(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
            },
        )