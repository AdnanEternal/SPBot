from typing import Any

from core.database_manager import DatabaseManager


class AntiSleepStore:
    TABLE = "anti_sleep_settings"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY",
                "chat_id": "INTEGER",
                "enabled": "INTEGER NOT NULL DEFAULT 0",
                "interval_minutes": (
                    "INTEGER NOT NULL DEFAULT 25"
                ),
            },
        )

        await self.db.insert(
            self.TABLE,
            {"id": 1},
            or_ignore=True,
        )

    async def get(self) -> dict[str, Any]:
        row = await self.db.select_one(
            self.TABLE,
            where={"id": 1},
        )

        return dict(row)

    async def enable(
        self,
        chat_id: int,
        interval_minutes: int = 25,
    ) -> None:
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                chat_id = ?,
                enabled = 1,
                interval_minutes = ?
            WHERE id = 1
            """,
            (
                chat_id,
                interval_minutes,
            ),
        )

    async def disable(self) -> None:
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET enabled = 0
            WHERE id = 1
            """
        )