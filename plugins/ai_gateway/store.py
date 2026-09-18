from __future__ import annotations

from typing import Any, Optional

from core.database_manager import DatabaseManager


class AIModelStore:
    TABLE = "ai_models"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "name": "TEXT NOT NULL UNIQUE",
                "provider": "TEXT NOT NULL",
                "model_id": "TEXT NOT NULL",
                "api_key": "TEXT",
                "base_url": "TEXT",
                "is_active": "INTEGER NOT NULL DEFAULT 0",
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
            indexes=["is_active", "provider"],
        )

    async def add(
        self,
        name: str,
        provider: str,
        model_id: str,
        api_key: Optional[str],
        base_url: Optional[str],
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "name": name.strip().lower(),
                "provider": provider.strip(),
                "model_id": model_id.strip(),
                "api_key": api_key,
                "base_url": base_url.strip() if base_url else None,
            },
        )

    async def get(self, name: str) -> Optional[dict[str, Any]]:
        row = await self.db.select_one(
            self.TABLE,
            where={"name": name.strip().lower()},
        )
        return dict(row) if row else None

    async def get_all(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            f"""
            SELECT *
            FROM {self.TABLE}
            ORDER BY is_active DESC, name ASC
            """
        )
        return [dict(row) for row in rows]

    async def get_active(self) -> Optional[dict[str, Any]]:
        row = await self.db.select_one(
            self.TABLE,
            where={"is_active": 1},
        )
        return dict(row) if row else None

    async def set_active(self, name: str) -> bool:
        normalized = name.strip().lower()
        model = await self.get(normalized)

        if model is None:
            return False

        await self.db.execute(
            f"UPDATE {self.TABLE} SET is_active = 0, updated_at = CURRENT_TIMESTAMP"
        )
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE name = ?
            """,
            (normalized,),
        )
        return True

    async def delete(self, name: str) -> bool:
        cursor = await self.db.delete(
            self.TABLE,
            {"name": name.strip().lower()},
        )
        return cursor.rowcount > 0

    async def update_api_key(
        self,
        name: str,
        api_key: Optional[str],
    ) -> bool:
        model = await self.get(name)
        if model is None:
            return False

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET api_key = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE name = ?
            """,
            (api_key, name.strip().lower()),
        )
        return True


class AIGroupSettingsStore:
    TABLE = "ai_group_settings"

    DEFAULT_SYSTEM_PROMPT = (
        "تو بوبی هستی؛ یک شخصیت دوستانه، طبیعی و شوخ‌طبع در یک گروه چت. "
        "مثل یک انسان عادی و متناسب با فضای گفتگو جواب بده. "
        "لازم نیست در هر پیام توضیح بدهی که هوش مصنوعی هستی. "
        "به اعضای گروه و اتفاقات قبلی گفتگو توجه کن و از context موجود استفاده کن."
    )

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "trigger": "TEXT",
                "system_prompt": "TEXT",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
        )

    async def _ensure(self, group_id: int) -> None:
        await self.db.insert(
            self.TABLE,
            {"group_id": group_id},
            or_ignore=True,
        )

    async def get(self, group_id: int) -> dict[str, Any]:
        await self._ensure(group_id)
        row = await self.db.select_one(
            self.TABLE,
            where={"group_id": group_id},
        )
        return dict(row)

    async def get_system_prompt(self, group_id: int) -> str:
        settings = await self.get(group_id)
        return settings["system_prompt"] or self.DEFAULT_SYSTEM_PROMPT

    async def set_system_prompt(
        self,
        group_id: int,
        prompt: str,
    ) -> None:
        await self._ensure(group_id)
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET system_prompt = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (prompt, group_id),
        )

    async def reset_system_prompt(self, group_id: int) -> None:
        await self._ensure(group_id)
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET system_prompt = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (group_id,),
        )

    async def get_trigger(self, group_id: int, default: str) -> str:
        settings = await self.get(group_id)
        return (settings["trigger"] or default).strip()

    async def set_trigger(self, group_id: int, trigger: str) -> None:
        await self._ensure(group_id)
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET trigger = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (trigger.strip(), group_id),
        )

    async def reset_trigger(self, group_id: int) -> None:
        await self._ensure(group_id)
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET trigger = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (group_id,),
        )


class AIMemoryStore:
    TABLE = "ai_memory_messages"
    SUMMARY_TABLE = "ai_memory_summaries"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_tables(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "group_id": "INTEGER NOT NULL",
                "user_id": "INTEGER",
                "role": "TEXT NOT NULL",
                "content": "TEXT NOT NULL",
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
            indexes=["group_id", "user_id"],
        )

        await self.db.create_table(
            self.SUMMARY_TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "summary": "TEXT NOT NULL",
                "through_message_id": "INTEGER NOT NULL DEFAULT 0",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
        )

    async def add_message(
        self,
        group_id: int,
        role: str,
        content: str,
        user_id: Optional[int] = None,
    ) -> int:
        cursor = await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
                "role": role,
                "content": content,
            },
        )
        return int(cursor.lastrowid)

    async def get_recent(
        self,
        group_id: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            f"""
            SELECT id, group_id, user_id, role, content, created_at
            FROM {self.TABLE}
            WHERE group_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (group_id, limit),
        )
        return [dict(row) for row in reversed(rows)]

    async def count(self, group_id: int) -> int:
        row = await self.db.fetchone(
            f"SELECT COUNT(*) AS count FROM {self.TABLE} WHERE group_id = ?",
            (group_id,),
        )
        return int(row["count"])

    async def get_summary(self, group_id: int) -> Optional[dict[str, Any]]:
        row = await self.db.select_one(
            self.SUMMARY_TABLE,
            where={"group_id": group_id},
        )
        return dict(row) if row else None

    async def save_summary(
        self,
        group_id: int,
        summary: str,
        through_message_id: int,
    ) -> None:
        await self.db.execute(
            f"""
            INSERT INTO {self.SUMMARY_TABLE}
                (group_id, summary, through_message_id)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                summary = excluded.summary,
                through_message_id = excluded.through_message_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (group_id, summary, through_message_id),
        )

    async def get_unsummarized(
        self,
        group_id: int,
        after_message_id: int,
        before_message_id: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            f"""
            SELECT id, group_id, user_id, role, content, created_at
            FROM {self.TABLE}
            WHERE group_id = ?
              AND id > ?
              AND id <= ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (group_id, after_message_id, before_message_id, limit),
        )
        return [dict(row) for row in rows]

    async def delete_through(
        self,
        group_id: int,
        message_id: int,
    ) -> None:
        await self.db.execute(
            f"""
            DELETE FROM {self.TABLE}
            WHERE group_id = ?
              AND id <= ?
            """,
            (group_id, message_id),
        )


class AIGatewayStore:
    def __init__(self, db: DatabaseManager) -> None:
        self.models = AIModelStore(db)
        self.groups = AIGroupSettingsStore(db)
        self.memory = AIMemoryStore(db)

    async def create_tables(self) -> None:
        await self.models.create_table()
        await self.groups.create_table()
        await self.memory.create_tables()
