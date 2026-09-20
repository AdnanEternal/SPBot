

import asyncio
from core.ttl_cache import TTLCache
from litellm import token_counter


from typing import Any, Optional

from core.database_manager import DatabaseManager


class AIModelStore:
    TABLE = "ai_models"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

        self._active_cache = TTLCache[
            str,
            dict[str, Any],
        ](
            max_entries=1,
            ttl_seconds=300,
        )


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

    async def get_active(
        self,
    ) -> Optional[dict[str, Any]]:
        cached = self._active_cache.get(
            "active"
        )

        if cached is not None:
            return dict(cached) if cached else None

        row = await self.db.select_one(
            self.TABLE,
            where={"is_active": 1},
        )

        if row is None:
            self._active_cache.set(
                "active",
                {},
            )
            return None

        model = dict(row)

        self._active_cache.set(
            "active",
            model,
        )

        return dict(model)

    async def set_active(
        self,
        name: str,
    ) -> bool:
        normalized = name.strip().lower()

        async with self.db.maintenance_lock:
            if self.db.connection is None:
                raise RuntimeError(
                    "Database connection is not available"
                )
            cursor = None
            try:
                await self.db.connection.execute(
                    f"""
                    UPDATE {self.TABLE}
                    SET is_active = 0,
                        updated_at = CURRENT_TIMESTAMP
                    """
                )

                cursor = await self.db.connection.execute(
                    f"""
                    UPDATE {self.TABLE}
                    SET is_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE name = ?
                    """,
                    (normalized,),
                )

                if cursor.rowcount <= 0:
                    await self.db.connection.rollback()
                    return False

                await self.db.connection.commit()

                self._active_cache.delete(
                    "active"
                )

                return True

            except Exception:
                try:
                    await self.db.connection.rollback()
                except Exception:
                    pass

                raise

            finally:
                try:
                    if cursor is not None:
                        await cursor.close()
                except Exception:
                    pass

    async def delete(
        self,
        name: str,
    ) -> bool:
        cursor = await self.db.delete(
            self.TABLE,
            {"name": name.strip().lower()},
        )

        deleted = cursor.rowcount > 0

        if deleted:
            self._active_cache.delete("active")

        return deleted

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
            (
                api_key, 
                name.strip().lower()
            ),
        )

        self._active_cache.delete(
            "active"
        )

        return True


class AIGroupSettingsStore:
    TABLE = "ai_group_settings"
    GLOBAL_GROUP_ID = 0

    DEFAULT_SYSTEM_PROMPT = (
        "تو «بوبی» هستی؛ یک عضو شوخ، بازیگوش، کمی لجباز و غیرقابل‌پیش‌بینیِ گروه.\n\n"
        "طبیعی و محاوره‌ای حرف بزن و بیش از حد رسمی نباش. "
        "لازم نیست همیشه موافق یا مؤدب باشی؛ می‌توانی مخالفت کنی، غر بزنی، "
        "طعنه بزنی و کل‌کل دوستانه راه بیندازی.\n\n"
        "در گروه همیشه دقت کن چه کسی چه چیزی گفته، اسم‌ها را قاطی نکن، "
        "موضوعات مختلف و replyها را از هم تشخیص بده و به تاریخچه‌ی گفتگو توجه کن.\n\n"
        "پاسخ‌ها معمولاً کوتاه، طبیعی و متناسب با فضا باشند. "
        "لازم نیست همیشه شوخی کنی و از تکرار شوخی‌ها خودداری کن.\n\n"
        "شخصیتت را حفظ کن، اما دقت را قربانی شوخی نکن. "
        "وقتی سؤال جدی است، دقیق جواب بده و وقتی مطمئن نیستی، حدس نزن."
    )

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

        self._trigger_cache = TTLCache[
            int,
            str,
        ](
            max_entries=512,
            ttl_seconds=900,
        )

        self._system_prompt_cache = TTLCache[
            int,
            str,
        ](
            max_entries=1,
            ttl_seconds=1800,
        )

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "trigger": "TEXT",
                "system_prompt": "TEXT",
                "updated_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
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

    async def get_system_prompt(
    self,
    group_id: int,
) -> str:
        cached = self._system_prompt_cache.get(
            self.GLOBAL_GROUP_ID
        )

        if cached is not None:
            return cached

        await self._ensure(
            self.GLOBAL_GROUP_ID
        )

        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": self.GLOBAL_GROUP_ID
            },
        )

        prompt = (
            row["system_prompt"]
            if row and row["system_prompt"]
            else self.DEFAULT_SYSTEM_PROMPT
        )

        self._system_prompt_cache.set(
            self.GLOBAL_GROUP_ID,
            prompt,
        )

        return prompt

    async def set_system_prompt(
        self,
        group_id: int,
        prompt: str,
    ) -> None:
        # group_id عمداً نادیده گرفته می‌شود.
        await self._ensure(
            self.GLOBAL_GROUP_ID
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET system_prompt = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (
                prompt,
                self.GLOBAL_GROUP_ID,
            ),
        )
        self._system_prompt_cache.set(
            self.GLOBAL_GROUP_ID,
            prompt,
        )

    async def reset_system_prompt(
        self,
        group_id: int,
    ) -> None:
        await self._ensure(
            self.GLOBAL_GROUP_ID
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET system_prompt = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (self.GLOBAL_GROUP_ID,),
        )
        self._system_prompt_cache.delete(
            self.GLOBAL_GROUP_ID
        )

    async def get_trigger(
        self,
        group_id: int,
        default: str,
) -> str:
        cached = self._trigger_cache.get(
            group_id
        )

        if cached is not None:
            return cached

        # بر خلاف نسخه قبلی، برای هر پیام
        # INSERT OR IGNORE نمی‌زنیم.
        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        trigger = (
            row["trigger"]
            if row and row["trigger"]
            else default
        ).strip()

        self._trigger_cache.set(
            group_id,
            trigger,
        )

        return trigger

    async def set_trigger(
    self,
    group_id: int,
    trigger: str,
) -> None:
        trigger = trigger.strip()

        await self._ensure(
            group_id
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET trigger = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (
                trigger,
                group_id,
            ),
        )

        self._trigger_cache.set(
            group_id,
            trigger,
        )

    async def reset_trigger(
        self,
        group_id: int,
    ) -> None:
        await self._ensure(
            group_id
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET trigger = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (group_id,),
        )

        self._trigger_cache.delete(group_id)
class AIMemorySettingsStore:
    TABLE = "ai_memory_settings"

    DEFAULT_TOKEN_LIMIT = 8000
    DEFAULT_MESSAGE_LIMIT = 500

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

        self._cache = TTLCache[
            int,
            dict[str, int],
        ](
            max_entries=256,
            ttl_seconds=900,
        )

    async def _get(
        self,
        group_id: int,
    ) -> dict[str, int]:
        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            return dict(cached)

        await self._ensure(
            group_id
        )

        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        settings = {
            "token_limit": int(
                row["token_limit"]
            ),
            "message_limit": int(
                row["message_limit"]
            ),
        }

        self._cache.set(
            group_id,
            settings,
        )

        return dict(settings)



    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "token_limit": (
                    f"INTEGER NOT NULL DEFAULT {self.DEFAULT_TOKEN_LIMIT}"
                ),
                "message_limit": (
                    f"INTEGER NOT NULL DEFAULT {self.DEFAULT_MESSAGE_LIMIT}"
                ),
                "updated_at": (
                    "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ),
            },
        )

        # Migration برای دیتابیس‌های قدیمی
        rows = await self.db.fetchall(
            f"PRAGMA table_info({self.TABLE})"
        )

        columns = {
            row["name"]
            for row in rows
        }

        if "message_limit" not in columns:
            await self.db.execute(
                f"""
                ALTER TABLE {self.TABLE}
                ADD COLUMN message_limit INTEGER
                NOT NULL DEFAULT {self.DEFAULT_MESSAGE_LIMIT}
                """
            )

    async def _ensure(self, group_id: int) -> None:
        await self.db.insert(
            self.TABLE,
            {"group_id": group_id},
            or_ignore=True,
        )

    async def get_token_limit(
        self,
        group_id: int,
    ) -> int:
        settings = await self._get(
            group_id
        )

        return settings["token_limit"]

    async def set_token_limit(
        self,
        group_id: int,
        token_limit: int,
    ) -> None:
        await self._ensure(group_id)

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET token_limit = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (
                token_limit,
                group_id,
            ),
        )

        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            cached["token_limit"] = token_limit

            self._cache.set(
                group_id,
                cached,
            )

    async def get_message_limit(
        self,
        group_id: int,
    ) -> int:
        settings = await self._get(
            group_id
        )

        return settings["message_limit"]
    
    
    async def set_message_limit(
        self,
        group_id: int,
        message_limit: int,
    ) -> None:
        await self._ensure(group_id)

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET message_limit = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (
                message_limit,
                group_id,
            ),
        )

        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            cached["message_limit"] = message_limit

            self._cache.set(
                group_id,
                cached,
            )

class AIMemoryStore:
    TABLE = "ai_memory_messages"
    SUMMARY_TABLE = "ai_memory_summaries"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def clear_group(
    self,
    group_id: int,
) -> None:
        await self.db.execute(
            f"""
            DELETE FROM {self.TABLE}
            WHERE group_id = ?
            """,
            (group_id,),
        )

        await self.db.execute(
            f"""
            DELETE FROM {self.SUMMARY_TABLE}
            WHERE group_id = ?
            """,
            (group_id,),
        )

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
    async def trim_group(
        self,
        group_id: int,
        keep: int,
    ) -> None:
        """فقط `keep` پیام آخر هر گروه رو نگه می‌داره."""
        await self.db.execute(
            f"""
            DELETE FROM {self.TABLE}
            WHERE group_id = ?
              AND id <= (
                  SELECT id FROM {self.TABLE}
                  WHERE group_id = ?
                  ORDER BY id DESC
                  LIMIT 1 OFFSET ?
              )
            """,
            (group_id, group_id, keep),
        )



class AIAPIKeyStore:
    TABLE = "ai_api_keys"

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "name": "TEXT NOT NULL UNIQUE",
                "provider": "TEXT NOT NULL",
                "api_key": "TEXT NOT NULL",
                "base_url": "TEXT",
                "models_url": "TEXT",
                "created_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
                "updated_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
            },
            indexes=["provider"],
        )

    async def add(
        self,
        name: str,
        provider: str,
        api_key: str,
        base_url: str | None = None,
        models_url: str | None = None,
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "name": name.strip().lower(),
                "provider": provider.strip(),
                "api_key": api_key.strip(),
                "base_url": (
                    base_url.strip()
                    if base_url
                    else None
                ),
                "models_url": (
                    models_url.strip()
                    if models_url
                    else None
                ),
            },
        )

    async def get(
        self,
        name: str,
    ) -> dict | None:
        row = await self.db.select_one(
            self.TABLE,
            where={
                "name": name.strip().lower()
            },
        )

        return dict(row) if row else None

    async def get_all(
        self,
    ) -> list[dict]:
        rows = await self.db.fetchall(
            f"""
            SELECT *
            FROM {self.TABLE}
            ORDER BY name ASC
            """
        )

        return [
            dict(row)
            for row in rows
        ]

    async def delete(
        self,
        name: str,
    ) -> bool:
        cursor = await self.db.delete(
            self.TABLE,
            {
                "name": name.strip().lower()
            },
        )

        return cursor.rowcount > 0




class AITimelineSettingsStore:
    TABLE = "ai_timeline_settings"

    DEFAULT_ENABLED = True
    DEFAULT_MESSAGE_LIMIT = 200

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY",
                "enabled": (
                    f"INTEGER NOT NULL DEFAULT "
                    f"{1 if self.DEFAULT_ENABLED else 0}"
                ),
                "message_limit": (
                    f"INTEGER NOT NULL DEFAULT "
                    f"{self.DEFAULT_MESSAGE_LIMIT}"
                ),
                "updated_at": (
                    "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ),
            },
        )

        await self.db.insert(
            self.TABLE,
            {
                "id": 1,
            },
            or_ignore=True,
        )

    async def get(self) -> dict:
        await self.create_table()

        row = await self.db.select_one(
            self.TABLE,
            where={
                "id": 1,
            },
        )

        return {
            "enabled": bool(row["enabled"]),
            "message_limit": int(row["message_limit"]),
        }

    async def set(
        self,
        enabled: bool,
        message_limit: int,
    ) -> None:
        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET enabled = ?,
                message_limit = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                1 if enabled else 0,
                message_limit,
            ),
        )



class AIGatewayStore:
    def __init__(self, db: DatabaseManager) -> None:
        self.models = AIModelStore(db)
        self.groups = AIGroupSettingsStore(db)
        self.memory = AIMemoryStore(db)
        self.memory_settings = AIMemorySettingsStore(db)
        self.api_keys = AIAPIKeyStore(db)
        self.timeline = AITimelineSettingsStore(db)

    async def create_tables(self) -> None:
        await self.models.create_table()
        await self.groups.create_table()
        await self.memory.create_tables()
        await self.memory_settings.create_table()
        await self.api_keys.create_table()
        await self.timeline.create_table()