from typing import Any

from core.database_manager import DatabaseManager
from core.ttl_cache import TTLCache

DEFAULT_MAX_VIOLATIONS = 3
DEFAULT_PUNISHMENT_TYPE = "mute"
DEFAULT_MUTE_HOURS = None


class ViolationStore:
    TABLE = "violations"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "group_id": "INTEGER NOT NULL",
                "user_id": "INTEGER NOT NULL",
                "reason": "TEXT NOT NULL",
                "created_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
            },
            indexes=[
                "group_id",
                "user_id",
            ],
        )

    async def add(
        self,
        group_id: int,
        user_id: int,
        reason: str,
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
                "reason": reason,
            },
        )

    async def get_count(
        self,
        group_id: int,
        user_id: int,
    ) -> int:
        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
            columns="COUNT(*) AS count",
        )

        return int(row["count"])

    async def get_users(
        self,
        group_id: int,
    ) -> list:
        return await self.db.fetchall(
            f"""
            SELECT
                user_id,
                COUNT(*) AS violation_count
            FROM {self.TABLE}
            WHERE group_id = ?
            GROUP BY user_id
            ORDER BY violation_count DESC
            """,
            (group_id,),
        )

    async def get_all(
        self,
        group_id: int,
        user_id: int,
    ) -> list:
        return await self.db.select_all(
            self.TABLE,
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
        )

    async def reset(
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


class GroupSettingsStore:
    TABLE = "violation_settings"
    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

        self._cache = TTLCache[
            int,
            dict[str, Any],
        ](
            max_entries=256,
            ttl_seconds=900,
        )

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": (
                    "INTEGER PRIMARY KEY"
                ),
                "max_violations": (
                    "INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_MAX_VIOLATIONS}"
                ),
                "punishment_type": (
                    "TEXT NOT NULL "
                    f"DEFAULT '{DEFAULT_PUNISHMENT_TYPE}'"
                ),
                "mute_hours": (
                    "INTEGER"
                ),
            },
        )

    async def _ensure_row(
        self,
        group_id: int,
    ) -> None:
        # ردیف را بساز
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
            },
            or_ignore=True,
        )

        # برای گروه‌های قدیمی که قبل از اضافه شدن
        # تنظیمات پیش‌فرض ساخته شده‌اند، NULL را اصلاح کن.
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                max_violations = COALESCE(
                    max_violations,
                    ?
                ),
                punishment_type = COALESCE(
                    punishment_type,
                    ?
                )
            WHERE group_id = ?
            """,
            (
                DEFAULT_MAX_VIOLATIONS,
                DEFAULT_PUNISHMENT_TYPE,
                group_id,
            ),
        )

    async def get(
        self,
        group_id: int,
    ) -> dict[str, Any]:

        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            return dict(cached)

        await self._ensure_row(
            group_id
        )

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

    async def set_max_violations(
        self,
        group_id: int,
        value: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "max_violations": value,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            cached["max_violations"] = value

            self._cache.set(
                group_id,
                cached,
            )

    async def set_punishment_mute(
        self,
        group_id: int,
        hours: int | None,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "punishment_type": "mute",
                "mute_hours": hours,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            cached["punishment_type"] = "mute"
            cached["mute_hours"] = hours

            self._cache.set(
                group_id,
                cached,
            )

    async def set_punishment_ban(
        self,
        group_id: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "punishment_type": "ban",
                "mute_hours": None,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            cached["punishment_type"] = "ban"
            cached["mute_hours"] = None

            self._cache.set(
                group_id,
                cached,
            )