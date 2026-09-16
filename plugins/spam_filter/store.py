from typing import Any

from core.database_manager import DatabaseManager

DEFAULT_FLOOD_COUNT = 5
DEFAULT_FLOOD_SECONDS = 10
DEFAULT_MAX_LINKS = 3
DEFAULT_MAX_REPEAT = 3


class SpamSettingsStore:
    """
    تنظیمات قابل‌شخصی‌سازی فیلتر اسپم هر گروه. اگه هیچ‌وقت با کامندها
    تنظیم نشن، همین مقادیر پیش‌فرض بالا استفاده می‌شن — یعنی پلاگین از
    همون اول بدون نیاز به هیچ کانفیگی کار می‌کنه.
    """

    TABLE = "spam_settings"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "flood_count": f"INTEGER NOT NULL DEFAULT {DEFAULT_FLOOD_COUNT}",
                "flood_seconds": f"INTEGER NOT NULL DEFAULT {DEFAULT_FLOOD_SECONDS}",
                "max_links": f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_LINKS}",
                "max_repeat": f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_REPEAT}",
            },
        )

    async def _ensure_row(self, group_id: int) -> None:
        await self.db.insert(self.TABLE, {"group_id": group_id}, or_ignore=True)

    async def get(self, group_id: int) -> dict[str, Any]:
        await self._ensure_row(group_id)
        row = await self.db.select_one(self.TABLE, where={"group_id": group_id})
        return dict(row)

    async def set_flood(self, group_id: int, count: int, seconds: int) -> None:
        await self._ensure_row(group_id)
        await self.db.update(
            self.TABLE,
            {"flood_count": count, "flood_seconds": seconds},
            where={"group_id": group_id},
        )

    async def set_max_links(self, group_id: int, count: int) -> None:
        await self._ensure_row(group_id)
        await self.db.update(self.TABLE, {"max_links": count}, where={"group_id": group_id})

    async def set_max_repeat(self, group_id: int, count: int) -> None:
        await self._ensure_row(group_id)
        await self.db.update(self.TABLE, {"max_repeat": count}, where={"group_id": group_id})
