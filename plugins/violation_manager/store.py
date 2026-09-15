from typing import Any

from core.database_manager import DatabaseManager

DEFAULT_MAX_VIOLATIONS = 3


class ViolationStore:
    """
    ثبت خودِ تخلف‌ها. هر تخلف مال یه (group_id, user_id) خاصه؛ کاربر ۲۵
    تو گروه ۱ و تو گروه ۶ کاملاً شمارش جدا از هم دارن.
    """

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
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
            indexes=["group_id", "user_id"],
        )

    async def add(self, group_id: int, user_id: int, reason: str) -> None:
        await self.db.insert(
            self.TABLE,
            {"group_id": group_id, "user_id": user_id, "reason": reason},
        )

    async def get_count(self, group_id: int, user_id: int) -> int:
        row = await self.db.select_one(
            self.TABLE,
            where={"group_id": group_id, "user_id": user_id},
            columns="COUNT(*) AS count",
        )
        return int(row["count"])

    async def get_users(self, group_id: int) -> list:
        return await self.db.fetchall(
            f"""
            SELECT user_id, COUNT(*) AS violation_count
            FROM {self.TABLE}
            WHERE group_id = ?
            GROUP BY user_id
            ORDER BY violation_count DESC
            """,
            (group_id,),
        )

    async def get_all(self, group_id: int, user_id: int) -> list:
        return await self.db.select_all(
            self.TABLE,
            where={"group_id": group_id, "user_id": user_id},
        )

    async def reset(self, group_id: int, user_id: int) -> None:
        await self.db.delete(self.TABLE, {"group_id": group_id, "user_id": user_id})


class GroupSettingsStore:
    """
    تنظیمات مجازات هر گروه: سقف تخلف مجاز، نوع مجازات (mute/ban)، و مدت
    میوت (فقط وقتی نوع مجازات mute ست شده باشه). هر گروه کاملاً مستقل از
    بقیه‌ی گروه‌هاست.

    چون این جدول per-group یه ردیف داره (نه چند ردیف مثل violations)،
    get() اول مطمئن می‌شه ردیف پیش‌فرض ساخته شده (_ensure_row) بعد
    می‌خونتش؛ اینجوری هیچ‌وقت لازم نیست جای دیگه‌ای چک کنیم "تنظیمات این
    گروه هنوز وجود داره یا نه".
    """

    TABLE = "violation_settings"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "max_violations": f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_VIOLATIONS}",
                "punishment_type": "TEXT",
                "mute_hours": "INTEGER",
            },
        )

    async def _ensure_row(self, group_id: int) -> None:
        await self.db.insert(self.TABLE, {"group_id": group_id}, or_ignore=True)

    async def get(self, group_id: int) -> dict[str, Any]:
        await self._ensure_row(group_id)
        row = await self.db.select_one(self.TABLE, where={"group_id": group_id})
        return dict(row)

    async def set_max_violations(self, group_id: int, value: int) -> None:
        await self._ensure_row(group_id)
        await self.db.update(
            self.TABLE, {"max_violations": value}, where={"group_id": group_id}
        )

    async def set_punishment_mute(self, group_id: int, hours: int) -> None:
        await self._ensure_row(group_id)
        await self.db.update(
            self.TABLE,
            {"punishment_type": "mute", "mute_hours": hours},
            where={"group_id": group_id},
        )

    async def set_punishment_ban(self, group_id: int) -> None:
        await self._ensure_row(group_id)
        await self.db.update(
            self.TABLE,
            {"punishment_type": "ban", "mute_hours": None},
            where={"group_id": group_id},
        )