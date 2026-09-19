

import asyncio

from litellm import token_counter
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
        # System Prompt همیشه از ردیف سراسری خوانده می‌شود.
        await self._ensure(
            self.GLOBAL_GROUP_ID
        )

        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": self.GLOBAL_GROUP_ID
            },
        )

        if not row:
            return self.DEFAULT_SYSTEM_PROMPT

        return (
            row["system_prompt"]
            or self.DEFAULT_SYSTEM_PROMPT
        )

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

    async def get_trigger(
        self,
        group_id: int,
        default: str,
    ) -> str:
        settings = await self.get(group_id)

        return (
            settings["trigger"]
            or default
        ).strip()

    async def set_trigger(
        self,
        group_id: int,
        trigger: str,
    ) -> None:
        await self._ensure(group_id)

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET trigger = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = ?
            """,
            (
                trigger.strip(),
                group_id,
            ),
        )

    async def reset_trigger(
        self,
        group_id: int,
    ) -> None:
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
class AIMemorySettingsStore:
    TABLE = "ai_memory_settings"
    DEFAULT_TOKEN_LIMIT = 8000

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "token_limit": (
                    f"INTEGER NOT NULL DEFAULT {self.DEFAULT_TOKEN_LIMIT}"
                ),
                "updated_at": (
                    "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ),
            },
        )

    async def _ensure(self, group_id: int) -> None:
        await self.db.insert(
            self.TABLE,
            {"group_id": group_id},
            or_ignore=True,
        )

    async def get_token_limit(self, group_id: int) -> int:
        await self._ensure(group_id)

        row = await self.db.select_one(
            self.TABLE,
            where={"group_id": group_id},
        )

        return int(row["token_limit"])

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
            (token_limit, group_id),
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


class AIMemoryManager:
    MAX_FETCH_MESSAGES = 1000
    KEEP_MESSAGES = 1000  # بیشتر از این تعداد پیام در هر گروه نگه داشته نمی‌شه
    MESSAGE_OVERHEAD_TOKENS = 4

    def __init__(self, store, settings_store):
        self.store = store
        self.settings = settings_store

    def _select_messages(
        self,
        rows: list[dict],
        system_prompt: str,
        token_limit: int,
        model_name: str | None,
    ) -> list[dict[str, str]]:
        """
        هر پیام فقط یک بار شمرده می‌شه (O(n)). این تابع sync هست و
        داخل thread اجرا می‌شه تا event loop رو بلاک نکنه.
        """
        counter_ok = model_name is not None

        def count(text: str) -> int:
            nonlocal counter_ok

            if counter_ok:
                try:
                    return (
                        int(token_counter(model=model_name, text=text))
                        + self.MESSAGE_OVERHEAD_TOKENS
                    )
                except Exception as exc:
                    print(f"⚠️ خطا در محاسبه توکن حافظه: {exc}")
                    counter_ok = False

            # fallback تقریبی
            return max(1, len(text) // 4) + self.MESSAGE_OVERHEAD_TOKENS

        total = count(system_prompt)
        selected: list[dict[str, str]] = []

        # از جدیدترین پیام به سمت قدیمی‌تر؛ جدیدترین پیام همیشه می‌مونه.
        for row in reversed(rows):
            cost = count(row["content"])

            if selected and total + cost > token_limit:
                break

            selected.append(
                {"role": row["role"], "content": row["content"]}
            )
            total += cost

        selected.reverse()

        # اگه با پاسخ assistant شروع شده، حذفش می‌کنیم.
        if selected and selected[0]["role"] == "assistant":
            selected.pop(0)

        return [
            {"role": "system", "content": system_prompt},
            *selected,
        ]

    async def build_context(
        self,
        group_id: int,
        system_prompt: str,
        gateway,
    ) -> list[dict[str, str]]:

        token_limit = await self.settings.get_token_limit(group_id)

        rows = await self.store.get_recent(
            group_id,
            self.MAX_FETCH_MESSAGES,
        )

        model_name = None

        try:
            model = await gateway.models.get_active()

            if model is not None:
                model_name = gateway._litellm_model(model)

        except Exception as exc:
            print(f"⚠️ خطا در گرفتن مدل فعال برای شمارش توکن: {exc}")

        return await asyncio.to_thread(
            self._select_messages,
            rows,
            system_prompt,
            token_limit,
            model_name,
        )

    async def trim(self, group_id: int) -> None:
        """پیام‌های خیلی قدیمی رو پاک می‌کنه تا دیتابیس بی‌نهایت بزرگ نشه."""
        try:
            await self.store.trim_group(group_id, self.KEEP_MESSAGES)
        except Exception as exc:
            print(f"⚠️ خطا در پاک‌سازی حافظه قدیمی: {exc}")

    def get_default_token_limit(self) -> int:
        return self.settings.DEFAULT_TOKEN_LIMIT

    @staticmethod
    def format_user_message(
        name: str,
        user_id: int,
        text: str,
    ) -> str:
        return (
            f"[کاربر: {name} | شناسه: {user_id}]\n"
            f"{text}"
        )

class AIAPIKeyStore:
    TABLE = "ai_api_keys"

    def __init__(self, db: DatabaseManager) -> None:
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
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
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
                "base_url": base_url.strip() if base_url else None,
                "models_url": models_url.strip() if models_url else None,
            },
        )

    async def get(self, name: str) -> dict | None:
        row = await self.db.select_one(
            self.TABLE,
            where={"name": name.strip().lower()},
        )

        return dict(row) if row else None

    async def get_all(self) -> list[dict]:
        rows = await self.db.fetchall(
            f"""
            SELECT *
            FROM {self.TABLE}
            ORDER BY name ASC
            """
        )

        return [dict(row) for row in rows]

    async def delete(self, name: str) -> bool:
        cursor = await self.db.delete(
            self.TABLE,
            {"name": name.strip().lower()},
        )

        return cursor.rowcount > 0

class AIGatewayStore:
    def __init__(self, db: DatabaseManager) -> None:
        self.models = AIModelStore(db)
        self.groups = AIGroupSettingsStore(db)
        self.memory = AIMemoryStore(db)
        self.memory_settings = AIMemorySettingsStore(db)
        self.api_keys = AIAPIKeyStore(db)

    async def create_tables(self) -> None:
        await self.models.create_table()
        await self.groups.create_table()
        await self.memory.create_tables()
        await self.memory_settings.create_table()
        await self.api_keys.create_table()