

import asyncio
from litellm import token_counter


from typing import Any, Optional

from datetime import (
    datetime,
    timezone,
)

from core.database_manager import DatabaseManager
from core.ttl_cache import TTLCache
from core.time_manager import (
    format_project_time,
    now,
)

from .providers import AIProviderStore

class AIModelStatisticsStore:
    TABLE = "ai_model_statistics"

    DEFAULT_SCORE = 50
    OWNER_WEIGHT = 0.70
    RELIABILITY_WEIGHT = 0.20
    LATENCY_WEIGHT = 0.10

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db




    @classmethod
    def calculate_overall_score(
        cls,
        stats: dict[str, Any],
    ) -> int:

        score = (
            float(stats["owner_score"])
            * cls.OWNER_WEIGHT
            + float(stats["reliability_score"])
            * cls.RELIABILITY_WEIGHT
            + float(stats["latency_score"])
            * cls.LATENCY_WEIGHT
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

    KEY_STATUS_AVAILABLE = (
        AIProviderStore.KEY_STATUS_AVAILABLE
    )
    KEY_STATUS_COOLDOWN = (
        AIProviderStore.KEY_STATUS_COOLDOWN
    )
    KEY_STATUS_INVALID = (
        AIProviderStore.KEY_STATUS_INVALID
    )
    KEY_STATUS_DISABLED = (
        AIProviderStore.KEY_STATUS_DISABLED
    )

    KEY_STATUSES = (
        AIProviderStore.KEY_STATUSES
    )

    def __init__(
        self,
        db: DatabaseManager,
        providers: AIProviderStore | None = None,
    ) -> None:

        self.db = db

        self.providers = (
            providers
            or AIProviderStore(db)
        )

        self._active_cache = TTLCache[
            str,
            dict[str, Any],
        ](
            max_entries=1,
            ttl_seconds=300,
        )

    async def _create_models_table(self) -> None:

        await self.db.create_table(
            self.TABLE,
            columns={
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                ),

                "name": (
                    "TEXT NOT NULL UNIQUE"
                ),

                # source of truth
                "provider_id": (
                    "INTEGER "
                    "REFERENCES ai_providers(id)"
                ),

                "model_id": (
                    "TEXT NOT NULL"
                ),

                # legacy fields kept temporarily
                # برای migration/backward compatibility
                "provider": (
                    "TEXT NOT NULL DEFAULT ''"
                ),

                "base_url": "TEXT",

                "is_active": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "created_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),

                "updated_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
            },

            # فعلاً provider_id را اینجا index نمی‌کنیم.
            # چون ممکن است جدول قدیمی باشد و این ستون هنوز وجود نداشته باشد.
            indexes=[
                "is_active",
            ],
        )

    async def _migrate_provider_links(self) -> None:

        rows = await self.db.fetchall(
            f"PRAGMA table_info({self.TABLE})"
        )

        columns = {
            row["name"]
            for row in rows
        }

        if "provider_id" not in columns:
            await self.db.execute(
                f"""
                ALTER TABLE {self.TABLE}
                ADD COLUMN provider_id INTEGER
                """
            )


        # =========================================================
        # PROVIDER_ID INDEX
        # =========================================================

        await self.db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS
            idx_{self.TABLE}_provider_id
            ON {self.TABLE} (provider_id)
            """
        )

        models = await self.db.fetchall(
            f"""
            SELECT
                id,
                provider_id,
                provider,
                base_url
            FROM {self.TABLE}
            ORDER BY id ASC
            """
        )

        for model in models:

            provider_id = model["provider_id"]

            if provider_id:
                provider = await self.providers.get(
                    int(provider_id)
                )

                if provider is not None:
                    continue

            provider_name = (
                str(
                    model["provider"]
                    or ""
                ).strip().lower()
            )

            if not provider_name:
                raise ValueError(
                    f"مدل #{model['id']} "
                    "Provider ندارد."
                )

            provider = (
                await self.providers.ensure_provider(
                    name=provider_name,
                    base_url=model["base_url"],
                    provider=provider_name,
                )
            )

            await self.db.execute(
                f"""
                UPDATE {self.TABLE}
                SET
                    provider_id = ?,
                    provider = ?,
                    base_url = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    provider["id"],
                    provider["name"],
                    provider["base_url"],
                    model["id"],
                ),
            )

    async def create_table(self) -> None:

        # -------------------------------------------------
        # Provider + shared key pool
        # -------------------------------------------------

        await self.providers.create_table()

        # -------------------------------------------------
        # Models
        # -------------------------------------------------

        await self._create_models_table()

        # -------------------------------------------------
        # Old model -> provider migration
        # -------------------------------------------------

        await self._migrate_provider_links()

        # -------------------------------------------------
        # Old model-specific keys -> provider pool
        # -------------------------------------------------

        await self.providers.migrate_legacy_model_keys()

    # =========================================================
    # MODEL CRUD
    # =========================================================

    async def add(
        self,
        name: str,
        provider: str,
        model_id: str,
    ) -> None:

        normalized_name = (
            name.strip().lower()
        )

        provider_name = (
            provider.strip().lower()
        )

        clean_model_id = (
            model_id.strip()
        )

        if not normalized_name:
            raise ValueError(
                "نام مدل نمی‌تواند خالی باشد."
            )

        if not provider_name:
            raise ValueError(
                "نام Provider نمی‌تواند خالی باشد."
            )

        if not clean_model_id:
            raise ValueError(
                "Model ID نمی‌تواند خالی باشد."
            )

        provider_row = (
            await self.providers.get(
                provider_name
            )
        )

        if provider_row is None:
            raise ValueError(
                f"Provider «{provider_name}» "
                "ثبت نشده است."
            )

        result = await self.db.insert(
            self.TABLE,
            {
                "name": normalized_name,
                "provider_id": provider_row["id"],
                "model_id": clean_model_id,

                # legacy compatibility
                "provider": provider_row["provider"],
                "base_url": provider_row["base_url"],
            },
        )

        if result.lastrowid is None:
            raise RuntimeError(
                "شناسه مدل ساخته‌شده قابل دریافت نیست."
            )

    async def get(
        self,
        name: str,
    ) -> dict[str, Any] | None:

        row = await self.db.fetchone(
            f"""
            SELECT
                m.id,
                m.name,
                m.provider_id,
                p.name AS provider_name,
                p.provider AS provider,
                m.model_id,
                p.base_url AS base_url,
                p.models_url AS models_url,
                m.is_active,
                m.created_at,
                m.updated_at
            FROM {self.TABLE} m
            INNER JOIN ai_providers p
                ON p.id = m.provider_id
            WHERE m.name = ?
            LIMIT 1
            """,
            (
                name.strip().lower(),
            ),
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
            SELECT
                m.id,
                m.name,
                m.provider_id,
                p.name AS provider_name,
                p.provider AS provider,
                m.model_id,
                p.base_url AS base_url,
                p.models_url AS models_url,
                m.is_active,
                m.created_at,
                m.updated_at
            FROM {self.TABLE} m
            INNER JOIN ai_providers p
                ON p.id = m.provider_id
            ORDER BY
                m.is_active DESC,
                m.name ASC
            """
        )

        return [
            dict(row)
            for row in rows
        ]

    async def get_active(
        self,
    ) -> dict[str, Any] | None:

        cached = self._active_cache.get(
            "active"
        )

        if cached is not None:
            return (
                dict(cached)
                if cached
                else None
            )

        row = await self.db.fetchone(
            f"""
            SELECT
                m.id,
                m.name,
                m.provider_id,
                p.name AS provider_name,
                p.provider AS provider,
                m.model_id,
                p.base_url AS base_url,
                p.models_url AS models_url,
                m.is_active,
                m.created_at,
                m.updated_at
            FROM {self.TABLE} m
            INNER JOIN ai_providers p
                ON p.id = m.provider_id
            WHERE m.is_active = 1
            LIMIT 1
            """
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

        normalized = (
            name.strip().lower()
        )

        async with self.db.maintenance_lock:

            cursor = None

            try:
                await self.db.connection.execute(
                    f"""
                    UPDATE {self.TABLE}
                    SET
                        is_active = 0,
                        updated_at = CURRENT_TIMESTAMP
                    """
                )

                cursor = (
                    await self.db.connection.execute(
                        f"""
                        UPDATE {self.TABLE}
                        SET
                            is_active = 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE name = ?
                        """,
                        (normalized,),
                    )
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
                await self.db.connection.rollback()
                raise

            finally:
                if cursor is not None:
                    await cursor.close()

    async def delete(
        self,
        name: str,
    ) -> bool:

        normalized = (
            name.strip().lower()
        )

        result = await self.db.delete(
            self.TABLE,
            {
                "name": normalized,
            },
        )

        deleted = (
            result.rowcount > 0
        )

        if deleted:
            self._active_cache.delete(
                "active"
            )

        # مهم:
        # Provider را حذف نمی‌کنیم.
        # چون ممکن است مدل‌های دیگری از همان Provider
        # هنوز از Pool استفاده کنند.

        return deleted

    # =========================================================
    # SHARED PROVIDER KEY POOL
    # =========================================================

    async def _get_provider_id(
        self,
        model_name: str,
    ) -> int | None:

        model = await self.get(
            model_name
        )

        if model is None:
            return None

        return int(
            model["provider_id"]
        )

    async def get_api_keys(
        self,
        model_name: str,
    ) -> list[dict[str, Any]]:

        provider_id = (
            await self._get_provider_id(
                model_name
            )
        )

        if provider_id is None:
            return []

        return await self.providers.get_api_keys(
            provider_id
        )

    async def get_active_api_key(
        self,
        model_name: str,
    ) -> dict[str, Any] | None:

        keys = await self.get_api_keys(
            model_name
        )

        for key in keys:
            if key["is_active"]:
                return key

        return None

    async def get_available_api_keys(
        self,
        model_name: str,
    ) -> list[dict[str, Any]]:

        provider_id = (
            await self._get_provider_id(
                model_name
            )
        )

        if provider_id is None:
            return []

        return await self.providers.get_available_api_keys(
            provider_id
        )

    async def get_api_key_candidates(
        self,
        model_name: str,
    ) -> list[dict[str, Any]]:

        provider_id = (
            await self._get_provider_id(
                model_name
            )
        )

        if provider_id is None:
            return []

        return await self.providers.get_api_key_candidates(
            provider_id
        )

    async def get_available_api_key(
        self,
        model_name: str,
    ) -> dict[str, Any] | None:

        keys = await self.get_available_api_keys(
            model_name
        )

        return keys[0] if keys else None

    async def set_api_key_status(
        self,
        model_name: str,
        key_number: int,
        status: str,
        *,
        cooldown_until: str | None = None,
        reason: str | None = None,
    ) -> bool:

        provider_id = (
            await self._get_provider_id(
                model_name
            )
        )

        if provider_id is None:
            return False

        return await self.providers.set_api_key_status(
            provider_id,
            key_number,
            status,
            cooldown_until=cooldown_until,
            reason=reason,
        )

    async def mark_api_key_available(
        self,
        model_name: str,
        key_number: int,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            model_name,
            key_number,
            self.KEY_STATUS_AVAILABLE,
            reason=reason,
        )

    async def mark_api_key_cooldown(
        self,
        model_name: str,
        key_number: int,
        cooldown_until: str | None,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            model_name,
            key_number,
            self.KEY_STATUS_COOLDOWN,
            cooldown_until=cooldown_until,
            reason=reason,
        )

    async def mark_api_key_invalid(
        self,
        model_name: str,
        key_number: int,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            model_name,
            key_number,
            self.KEY_STATUS_INVALID,
            reason=reason,
        )

    async def mark_api_key_disabled(
        self,
        model_name: str,
        key_number: int,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            model_name,
            key_number,
            self.KEY_STATUS_DISABLED,
            reason=reason,
        )

    async def add_api_key(
        self,
        model_name: str,
        api_key: str,
    ) -> int | None:

        provider_id = (
            await self._get_provider_id(
                model_name
            )
        )

        if provider_id is None:
            return None

        return await self.providers.add_api_key(
            provider_id,
            api_key,
        )

    async def activate_api_key(
        self,
        model_name: str,
        key_number: int,
    ) -> bool:

        provider_id = (
            await self._get_provider_id(
                model_name
            )
        )

        if provider_id is None:
            return False

        return await self.providers.activate_api_key(
            provider_id,
            key_number,
        )

    async def update_api_key(
        self,
        model_name: str,
        key_number: int,
        api_key: str,
    ) -> bool:

        provider_id = (
            await self._get_provider_id(
                model_name
            )
        )

        if provider_id is None:
            return False

        return await self.providers.update_api_key(
            provider_id,
            key_number,
            api_key,
        )

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
    ):
        self.providers = AIProviderStore(db)

        self.models = AIModelStore(
            db,
            self.providers,
        )

        self.api_keys = AIAPIKeyStore(db)

        self.groups = AIGroupSettingsStore(db)
        self.memory = AIMemoryStore(db)
        self.memory_settings = AIMemorySettingsStore(db)
        self.timeline = AITimelineSettingsStore(db)
        self.telemetry = AITelemetrySettingsStore(db)
        self.model_statistics = AIModelStatisticsStore(db)

    async def create_tables(self) -> None:
        await self.models.create_table()
        await self.groups.create_table()
        await self.memory.create_tables()
        await self.memory_settings.create_table()
        await self.timeline.create_table()
        await self.telemetry.create_table()
        await self.model_statistics.create_table()
        await self.api_keys.create_table()