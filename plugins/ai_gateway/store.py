

import asyncio
from litellm import token_counter


from typing import Any, Optional

from core.database_manager import DatabaseManager
from core.ttl_cache import TTLCache
from core.time_manager import (
    format_project_time,
    now,
)

class AIModelStatisticsStore:
    TABLE = "ai_model_statistics"

    DEFAULT_SCORE = 50

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "model_name": (
                    "TEXT PRIMARY KEY"
                ),

                # -------------------------
                # Scores
                # -------------------------

                "owner_score": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {self.DEFAULT_SCORE} "
                    "CHECK(owner_score BETWEEN 0 AND 100)"
                ),

                "reliability_score": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {self.DEFAULT_SCORE} "
                    "CHECK(reliability_score BETWEEN 0 AND 100)"
                ),

                "latency_score": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {self.DEFAULT_SCORE} "
                    "CHECK(latency_score BETWEEN 0 AND 100)"
                ),

                # -------------------------
                # Real request counters
                # -------------------------

                "success_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "failure_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "rate_limit_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "quota_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "timeout_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "context_error_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "auth_error_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "server_error_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "unknown_error_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                # -------------------------
                # Real request latency
                # -------------------------

                "total_latency_ms": (
                    "REAL NOT NULL DEFAULT 0"
                ),

                "average_latency_ms": (
                    "REAL NOT NULL DEFAULT 0"
                ),

                # -------------------------
                # Last real request state
                # -------------------------

                "last_success_at": "TEXT",
                "last_failure_at": "TEXT",
                "last_error": "TEXT",

                # -------------------------
                # Ping
                # -------------------------

                "ping_success_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "ping_failure_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "ping_total_latency_ms": (
                    "REAL NOT NULL DEFAULT 0"
                ),

                "ping_average_latency_ms": (
                    "REAL NOT NULL DEFAULT 0"
                ),

                "ping_last_success_at": "TEXT",
                "ping_last_failure_at": "TEXT",
                "ping_last_error": "TEXT",

                "updated_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
            },
        )

        # -------------------------
        # Migration
        # -------------------------

        rows = await self.db.fetchall(
            f"PRAGMA table_info({self.TABLE})"
        )

        columns = {
            row["name"]
            for row in rows
        }

        migrations = {
            "ping_success_count": (
                "INTEGER NOT NULL DEFAULT 0"
            ),
            "ping_failure_count": (
                "INTEGER NOT NULL DEFAULT 0"
            ),
            "ping_total_latency_ms": (
                "REAL NOT NULL DEFAULT 0"
            ),
            "ping_average_latency_ms": (
                "REAL NOT NULL DEFAULT 0"
            ),
            "ping_last_success_at": "TEXT",
            "ping_last_failure_at": "TEXT",
            "ping_last_error": "TEXT",
        }

        for column, definition in migrations.items():

            if column in columns:
                continue

            await self.db.execute(
                f"""
                ALTER TABLE {self.TABLE}
                ADD COLUMN {column} {definition}
                """
            )
            
    async def ensure(
        self,
        model_name: str,
    ) -> None:
        normalized = (
            model_name.strip().lower()
        )

        if not normalized:
            raise ValueError(
                "نام مدل نمی‌تواند خالی باشد."
            )

        await self.db.insert(
            self.TABLE,
            {
                "model_name": normalized,
            },
            or_ignore=True,
        )

    async def get(
        self,
        model_name: str,
    ) -> dict[str, Any] | None:

        normalized = (
            model_name.strip().lower()
        )

        await self.ensure(
            normalized
        )

        row = await self.db.select_one(
            self.TABLE,
            where={
                "model_name": normalized,
            },
        )

        return (
            dict(row)
            if row is not None
            else None
        )

    async def get_all(
        self,
    ) -> list[dict[str, Any]]:

        rows = await self.db.fetchall(
            f"""
            SELECT *
            FROM {self.TABLE}
            ORDER BY owner_score DESC
            """
        )

        return [
            dict(row)
            for row in rows
        ]

    async def set_scores(
        self,
        model_name: str,
        *,
        owner_score: int | None = None,
        reliability_score: int | None = None,
        latency_score: int | None = None,
    ) -> None:

        normalized = (
            model_name.strip().lower()
        )

        await self.ensure(
            normalized
        )

        values: dict[str, Any] = {}

        if owner_score is not None:
            values["owner_score"] = self._validate_score(
                owner_score
            )

        if reliability_score is not None:
            values["reliability_score"] = self._validate_score(
                reliability_score
            )

        if latency_score is not None:
            values["latency_score"] = self._validate_score(
                latency_score
            )

        if not values:
            return

        assignments = ", ".join(
            f"{column} = ?"
            for column in values
        )

        parameters = list(
            values.values()
        )

        parameters.append(
            normalized
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                {assignments},
                updated_at = CURRENT_TIMESTAMP
            WHERE model_name = ?
            """,
            tuple(parameters),
        )



    async def record_attempt_error(
        self,
        model_name: str,
        error_category: str,
        error: str,
    ) -> None:

        normalized = (
            model_name.strip().lower()
        )

        await self.ensure(
            normalized
        )

        category_columns = {
            "RATE_LIMIT": "rate_limit_count",
            "QUOTA": "quota_count",
            "TIMEOUT": "timeout_count",
            "CONTEXT": "context_error_count",
            "AUTHENTICATION": "auth_error_count",
            "SERVER_ERROR": "server_error_count",
            "UNKNOWN": "unknown_error_count",
        }

        error_column = (
            category_columns.get(
                error_category,
                "unknown_error_count",
            )
        )

        timestamp = format_project_time(
            now()
        )

        safe_error = str(
            error or ""
        ).strip()

        if len(safe_error) > 2000:
            safe_error = (
                safe_error[:1997]
                + "..."
            )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                {error_column} =
                    {error_column} + 1,

                last_failure_at = ?,

                last_error = ?,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE model_name = ?
            """,
            (
                timestamp,
                safe_error,
                normalized,
            ),
        )

    async def record_ping_success(
        self,
        model_name: str,
        latency_ms: float,
    ) -> None:

        normalized = (
            model_name.strip().lower()
        )

        await self.ensure(
            normalized
        )

        latency_ms = max(
            0.0,
            float(latency_ms),
        )

        timestamp = format_project_time(
            now()
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                ping_success_count =
                    ping_success_count + 1,

                ping_total_latency_ms =
                    ping_total_latency_ms + ?,

                ping_average_latency_ms =
                    (
                        ping_total_latency_ms + ?
                    ) / (
                        ping_success_count + 1
                    ),

                ping_last_success_at = ?,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE model_name = ?
            """,
            (
                latency_ms,
                latency_ms,
                timestamp,
                normalized,
            ),
        )


    async def record_ping_failure(
        self,
        model_name: str,
        latency_ms: float,
        error: str,
    ) -> None:

        normalized = (
            model_name.strip().lower()
        )

        await self.ensure(
            normalized
        )

        timestamp = format_project_time(
            now()
        )

        safe_error = str(
            error or ""
        ).strip()

        if len(safe_error) > 2000:
            safe_error = (
                safe_error[:1997]
                + "..."
            )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                ping_failure_count =
                    ping_failure_count + 1,

                ping_last_failure_at = ?,

                ping_last_error = ?,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE model_name = ?
            """,
            (
                timestamp,
                safe_error,
                normalized,
            ),
        )

    async def record_success(
        self,
        model_name: str,
        latency_ms: float,
    ) -> None:

        normalized = (
            model_name.strip().lower()
        )

        await self.ensure(
            normalized
        )

        latency_ms = max(
            0.0,
            float(latency_ms),
        )

        timestamp = format_project_time(
            now()
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                success_count =
                    success_count + 1,

                total_latency_ms =
                    total_latency_ms + ?,

                average_latency_ms =
                    (
                        total_latency_ms + ?
                    ) / (
                        success_count + 1
                    ),

                last_success_at = ?,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE model_name = ?
            """,
            (
                latency_ms,
                latency_ms,
                timestamp,
                normalized,
            ),
        )

        await self.recalculate_scores(
            normalized
        )


    async def record_failure(
        self,
        model_name: str,
    ) -> None:

        normalized = (
            model_name.strip().lower()
        )

        await self.ensure(
            normalized
        )

        timestamp = format_project_time(
            now()
        )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                failure_count =
                    failure_count + 1,

                last_failure_at = ?,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE model_name = ?
            """,
            (
                timestamp,
                normalized,
            ),
        )
        
        await self.recalculate_scores(
            normalized
        )


    @staticmethod
    def _calculate_reliability_score(
        success_count: int,
        failure_count: int,
    ) -> int:

        total_requests = (
            success_count
            + failure_count
        )

        if total_requests <= 0:
            return 50

        score = (
            success_count
            / total_requests
            * 100
        )

        return int(
            round(
                max(
                    0,
                    min(
                        100,
                        score,
                    ),
                )
            )
        )


    @staticmethod
    def _calculate_latency_score(
        average_latency_ms: float,
    ) -> int:

        latency = max(
            0.0,
            float(average_latency_ms),
        )

        # سریع‌تر از 500ms = حداکثر امتیاز
        if latency <= 500:
            return 100

        # کندتر از 16s = حداقل امتیاز
        if latency >= 16000:
            return 0

        # نقاط مرجع:
        # 500ms  -> 100
        # 1000ms -> 90
        # 2000ms -> 75
        # 4000ms -> 50
        # 8000ms -> 25
        # 16000ms -> 0

        points = (
            (500, 100),
            (1000, 90),
            (2000, 75),
            (4000, 50),
            (8000, 25),
            (16000, 0),
        )

        import math

        log_latency = math.log2(
            latency
        )

        for index in range(
            len(points) - 1
        ):

            low_latency, low_score = (
                points[index]
            )

            high_latency, high_score = (
                points[index + 1]
            )

            if (
                low_latency
                <= latency
                <= high_latency
            ):

                low_log = math.log2(
                    low_latency
                )

                high_log = math.log2(
                    high_latency
                )

                ratio = (
                    log_latency - low_log
                ) / (
                    high_log - low_log
                )

                score = (
                    low_score
                    + (
                        high_score
                        - low_score
                    )
                    * ratio
                )

                return int(
                    round(
                        max(
                            0,
                            min(
                                100,
                                score,
                            ),
                        )
                    )
                )

        return 50

    async def recalculate_scores(
        self,
        model_name: str,
    ) -> None:

        normalized = (
            model_name.strip().lower()
        )

        stats = await self.get(
            normalized
        )

        if stats is None:
            return

        reliability_score = (
            self._calculate_reliability_score(
                stats["success_count"],
                stats["failure_count"],
            )
        )

        if (
            stats["success_count"] <= 0
        ):
            latency_score = 50

        else:
            latency_score = (
                self._calculate_latency_score(
                    stats["average_latency_ms"]
                )
            )

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                reliability_score = ?,
                latency_score = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE model_name = ?
            """,
            (
                reliability_score,
                latency_score,
                normalized,
            ),
        )

        
    @staticmethod
    def _validate_score(
        score: int,
    ) -> int:
        score = int(score)

        if not 0 <= score <= 100:
            raise ValueError(
                "امتیاز باید بین 0 تا 100 باشد."
            )

        return score





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
    DEFAULT_MESSAGE_LIMIT = 50
    DEFAULT_MAX_CHARS = 26000

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
                "max_chars": (
                    f"INTEGER NOT NULL DEFAULT "
                    f"{self.DEFAULT_MAX_CHARS}"
                ),
                "updated_at": (
                    "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ),
            },
        )

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

        if "max_chars" not in columns:
            await self.db.execute(
                f"""
                ALTER TABLE {self.TABLE}
                ADD COLUMN max_chars INTEGER
                NOT NULL DEFAULT {self.DEFAULT_MAX_CHARS}
                """
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
            "message_limit": int(
                row["message_limit"]
            ),
            "max_chars": int(
                row["max_chars"]
            ),
        }

    async def get_max_chars(self) -> int:
        settings = await self.get()

        return int(
            settings["max_chars"]
        )


    async def set_max_chars(
        self,
        max_chars: int,
    ) -> None:
        max_chars = int(max_chars)

        await self.create_table()

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET max_chars = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                max_chars,
            ),
        )

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







class AITelemetrySettingsStore:
    TABLE = "ai_telemetry_settings"

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY",
                "enabled": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),
                "target_group_id": "INTEGER",
                "updated_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
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
            "enabled": bool(
                row["enabled"]
            ),
            "target_group_id": (
                int(
                    row["target_group_id"]
                )
                if row["target_group_id"]
                is not None
                else None
            ),
        }

    async def set_target(
        self,
        group_id: int,
    ) -> None:

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET enabled = 1,
                target_group_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                int(group_id),
            ),
        )

    async def clear_target(self) -> None:

        await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET enabled = 0,
                target_group_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """
        )







class AIGatewayStore:
    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:

        self.models = AIModelStore(db)
        self.model_statistics = AIModelStatisticsStore(db)
        self.groups = AIGroupSettingsStore(db)
        self.memory = AIMemoryStore(db)
        self.memory_settings = AIMemorySettingsStore(db)
        self.api_keys = AIAPIKeyStore(db)
        self.timeline = AITimelineSettingsStore(db)
        self.telemetry = AITelemetrySettingsStore(db)


    async def create_tables(self) -> None:
        await self.models.create_table()
        await self.model_statistics.create_table()
        await self.groups.create_table()
        await self.memory.create_tables()
        await self.memory_settings.create_table()
        await self.api_keys.create_table()
        await self.timeline.create_table()
        await self.telemetry.create_table()