from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class AIProviderStore:
    TABLE = "ai_providers"
    KEY_TABLE = "ai_provider_api_keys"

    KEY_STATUS_AVAILABLE = "AVAILABLE"
    KEY_STATUS_COOLDOWN = "COOLDOWN"
    KEY_STATUS_INVALID = "INVALID"
    KEY_STATUS_DISABLED = "DISABLED"

    KEY_STATUSES = frozenset(
        {
            KEY_STATUS_AVAILABLE,
            KEY_STATUS_COOLDOWN,
            KEY_STATUS_INVALID,
            KEY_STATUS_DISABLED,
        }
    )

    def __init__(self, db):
        self.db = db

    # =========================================================
    # PROVIDERS
    # =========================================================

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",

                # نام داخلی Provider در SPBot
                # مثال: gemini
                "name": "TEXT NOT NULL UNIQUE",

                # Provider مورد استفاده LiteLLM
                # مثال: openai
                "provider": "TEXT NOT NULL DEFAULT ''",

                "base_url": "TEXT NOT NULL DEFAULT ''",
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
            indexes=[
                "name",
            ],
        )

        await self.db.create_table(
            self.KEY_TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",

                "provider_id": (
                    "INTEGER NOT NULL "
                    "REFERENCES ai_providers(id) "
                    "ON DELETE CASCADE"
                ),

                "key_number": (
                    "INTEGER NOT NULL"
                ),

                "api_key": (
                    "TEXT NOT NULL"
                ),

                "is_active": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),

                "status": (
                    "TEXT NOT NULL "
                    "DEFAULT 'AVAILABLE'"
                ),

                "status_reason": "TEXT",

                "cooldown_until": "TEXT",

                "created_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),

                "updated_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
            },
            unique=[
                (
                    "provider_id",
                    "key_number",
                ),
                (
                    "provider_id",
                    "api_key",
                ),
            ],
            indexes=[
                "provider_id",
                "is_active",
                "status",
            ],
        )

    async def get(
        self,
        provider: str | int,
    ) -> dict[str, Any] | None:

        if isinstance(provider, int):
            row = await self.db.fetchone(
                f"""
                SELECT *
                FROM {self.TABLE}
                WHERE id = ?
                LIMIT 1
                """,
                (provider,),
            )
        else:
            row = await self.db.select_one(
                self.TABLE,
                where={
                    "name": provider.strip().lower()
                },
            )

        return (
            dict(row)
            if row is not None
            else None
        )

    async def get_all(self) -> list[dict[str, Any]]:
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

    async def add(
        self,
        name: str,
        provider: str,
        base_url: str,
        models_url: str | None = None,
    ) -> int:

        normalized_name = (
            name.strip().lower()
        )

        normalized_provider = (
            provider.strip().lower()
        )

        clean_base_url = (
            base_url.strip().rstrip("/")
        )

        clean_models_url = (
            models_url.strip().rstrip("/")
            if models_url
            else None
        )

        if not normalized_name:
            raise ValueError(
                "نام Provider نمی‌تواند خالی باشد."
            )

        if not normalized_provider:
            raise ValueError(
                "LiteLLM Provider نمی‌تواند خالی باشد."
            )

        if not clean_base_url:
            raise ValueError(
                "Base URL نمی‌تواند خالی باشد."
            )

        existing = await self.get(
            normalized_name
        )

        if existing is not None:
            raise ValueError(
                f"Provider «{normalized_name}» "
                "قبلاً ثبت شده است."
            )

        result = await self.db.insert(
            self.TABLE,
            {
                "name": normalized_name,
                "provider": normalized_provider,
                "base_url": clean_base_url,
                "models_url": clean_models_url,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError(
                "شناسه Provider ساخته‌شده قابل دریافت نیست."
            )

        return int(
            result.lastrowid
        )
    
    async def update(
        self,
        name: str,
        provider: str,
        base_url: str,
        models_url: str | None = None,
    ) -> bool:

        normalized_name = (
            name.strip().lower()
        )

        normalized_provider = (
            provider.strip().lower()
        )

        clean_base_url = (
            base_url.strip().rstrip("/")
        )

        clean_models_url = (
            models_url.strip().rstrip("/")
            if models_url
            else None
        )

        if not normalized_name:
            raise ValueError(
                "نام Provider نمی‌تواند خالی باشد."
            )

        if not normalized_provider:
            raise ValueError(
                "LiteLLM Provider نمی‌تواند خالی باشد."
            )

        if not clean_base_url:
            raise ValueError(
                "Base URL نمی‌تواند خالی باشد."
            )

        result = await self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET
                provider = ?,
                base_url = ?,
                models_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE name = ?
            """,
            (
                normalized_provider,
                clean_base_url,
                clean_models_url,
                normalized_name,
            ),
        )

        return result.rowcount > 0


    async def delete(
        self,
        name: str,
    ) -> bool:

        normalized_name = (
            name.strip().lower()
        )

        provider = await self.get(
            normalized_name
        )

        if provider is None:
            return False

        model_row = await self.db.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM ai_models
            WHERE provider_id = ?
            """,
            (
                int(provider["id"]),
            ),
        )

        if model_row and int(model_row["count"]) > 0:
            raise ValueError(
                f"Provider «{normalized_name}» "
                "هنوز توسط یک یا چند Model استفاده می‌شود."
            )

        result = await self.db.execute(
            f"""
            DELETE FROM {self.TABLE}
            WHERE id = ?
            """,
            (
                int(provider["id"]),
            ),
        )

        return result.rowcount > 0

    # =========================================================
    # COOLDOWN
    # =========================================================

    @staticmethod
    def _is_cooldown_expired(
        cooldown_until: str | None,
    ) -> bool:

        if not cooldown_until:
            return False

        try:
            expires_at = datetime.fromisoformat(
                cooldown_until
            )

        except (
            TypeError,
            ValueError,
        ):
            return False

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(
                tzinfo=timezone.utc
            )

        return (
            expires_at
            <= datetime.now(
                timezone.utc
            )
        )

    async def _restore_expired_cooldowns(
        self,
        provider_id: int,
    ) -> None:

        rows = await self.db.fetchall(
            f"""
            SELECT
                id,
                cooldown_until
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
              AND status = 'COOLDOWN'
              AND cooldown_until IS NOT NULL
            """,
            (provider_id,),
        )

        for row in rows:

            if not self._is_cooldown_expired(
                row["cooldown_until"]
            ):
                continue

            await self.db.execute(
                f"""
                UPDATE {self.KEY_TABLE}
                SET
                    status = 'AVAILABLE',
                    status_reason = NULL,
                    cooldown_until = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'COOLDOWN'
                """,
                (row["id"],),
            )

    # =========================================================
    # KEY POOL
    # =========================================================

    async def get_api_keys(
        self,
        provider: str | int,
    ) -> list[dict[str, Any]]:

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return []

        provider_id = int(
            provider_row["id"]
        )

        await self._restore_expired_cooldowns(
            provider_id
        )

        rows = await self.db.fetchall(
            f"""
            SELECT
                id,
                provider_id,
                key_number,
                api_key,
                is_active,
                status,
                status_reason,
                cooldown_until,
                created_at,
                updated_at
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
            ORDER BY key_number ASC
            """,
            (provider_id,),
        )

        return [
            dict(row)
            for row in rows
        ]

    async def get_available_api_keys(
        self,
        provider: str | int,
    ) -> list[dict[str, Any]]:

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return []

        provider_id = int(
            provider_row["id"]
        )

        await self._restore_expired_cooldowns(
            provider_id
        )

        rows = await self.db.fetchall(
            f"""
            SELECT
                id,
                provider_id,
                key_number,
                api_key,
                is_active,
                status,
                status_reason,
                cooldown_until,
                created_at,
                updated_at
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
              AND status = 'AVAILABLE'
            ORDER BY
                is_active DESC,
                key_number ASC
            """,
            (provider_id,),
        )

        return [
            dict(row)
            for row in rows
        ]

    async def get_api_key_candidates(
        self,
        provider: str | int,
    ) -> list[dict[str, Any]]:

        available = (
            await self.get_available_api_keys(
                provider
            )
        )

        if available:
            return available

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return []

        provider_id = int(
            provider_row["id"]
        )

        rows = await self.db.fetchall(
            f"""
            SELECT
                id,
                provider_id,
                key_number,
                api_key,
                is_active,
                status,
                status_reason,
                cooldown_until,
                created_at,
                updated_at
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
              AND status = 'COOLDOWN'
            ORDER BY
                CASE
                    WHEN cooldown_until IS NULL
                    THEN 1
                    ELSE 0
                END ASC,
                cooldown_until ASC,
                is_active DESC,
                key_number ASC
            """,
            (provider_id,),
        )

        return [
            dict(row)
            for row in rows
        ]

    async def add_api_key(
        self,
        provider: str | int,
        api_key: str,
    ) -> int | None:

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return None

        clean_key = api_key.strip()

        if not clean_key:
            raise ValueError(
                "API Key نمی‌تواند خالی باشد."
            )

        provider_id = int(
            provider_row["id"]
        )

        existing = await self.db.fetchone(
            f"""
            SELECT id
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
              AND api_key = ?
            LIMIT 1
            """,
            (
                provider_id,
                clean_key,
            ),
        )

        if existing is not None:
            return 0

        row = await self.db.fetchone(
            f"""
            SELECT
                COALESCE(
                    MAX(key_number),
                    0
                ) + 1 AS next_number
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
            """,
            (provider_id,),
        )

        key_number = int(
            row["next_number"]
        )

        active = await self.db.fetchone(
            f"""
            SELECT id
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
              AND is_active = 1
            LIMIT 1
            """,
            (provider_id,),
        )

        await self.db.insert(
            self.KEY_TABLE,
            {
                "provider_id": provider_id,
                "key_number": key_number,
                "api_key": clean_key,
                "is_active": (
                    0
                    if active is not None
                    else 1
                ),
                "status": "AVAILABLE",
            },
        )

        return key_number

    async def set_api_key_status(
        self,
        provider: str | int,
        key_number: int,
        status: str,
        *,
        cooldown_until: str | None = None,
        reason: str | None = None,
    ) -> bool:

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return False

        status = status.strip().upper()

        if status not in self.KEY_STATUSES:
            raise ValueError(
                f"وضعیت API Key نامعتبر است: {status}"
            )

        if status != self.KEY_STATUS_COOLDOWN:
            cooldown_until = None

        provider_id = int(
            provider_row["id"]
        )

        result = await self.db.execute(
            f"""
            UPDATE {self.KEY_TABLE}
            SET
                status = ?,
                status_reason = ?,
                cooldown_until = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE provider_id = ?
              AND key_number = ?
            """,
            (
                status,
                (
                    reason.strip().upper()
                    if reason
                    else None
                ),
                cooldown_until,
                provider_id,
                int(key_number),
            ),
        )

        return result.rowcount > 0

    async def mark_api_key_available(
        self,
        provider: str | int,
        key_number: int,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            provider,
            key_number,
            self.KEY_STATUS_AVAILABLE,
            reason=reason,
        )

    async def mark_api_key_cooldown(
        self,
        provider: str | int,
        key_number: int,
        cooldown_until: str | None,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            provider,
            key_number,
            self.KEY_STATUS_COOLDOWN,
            cooldown_until=cooldown_until,
            reason=reason,
        )

    async def mark_api_key_invalid(
        self,
        provider: str | int,
        key_number: int,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            provider,
            key_number,
            self.KEY_STATUS_INVALID,
            reason=reason,
        )

    async def mark_api_key_disabled(
        self,
        provider: str | int,
        key_number: int,
        reason: str | None = None,
    ) -> bool:

        return await self.set_api_key_status(
            provider,
            key_number,
            self.KEY_STATUS_DISABLED,
            reason=reason,
        )

    async def activate_api_key(
        self,
        provider: str | int,
        key_number: int,
    ) -> bool:

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return False

        provider_id = int(
            provider_row["id"]
        )

        target = await self.db.fetchone(
            f"""
            SELECT id
            FROM {self.KEY_TABLE}
            WHERE provider_id = ?
              AND key_number = ?
            LIMIT 1
            """,
            (
                provider_id,
                int(key_number),
            ),
        )

        if target is None:
            return False

        await self.db.execute(
            f"""
            UPDATE {self.KEY_TABLE}
            SET
                is_active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE provider_id = ?
            """,
            (provider_id,),
        )

        result = await self.db.execute(
            f"""
            UPDATE {self.KEY_TABLE}
            SET
                is_active = 1,
                status = 'AVAILABLE',
                status_reason = NULL,
                cooldown_until = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE provider_id = ?
              AND key_number = ?
            """,
            (
                provider_id,
                int(key_number),
            ),
        )

        return result.rowcount > 0

    async def update_api_key(
        self,
        provider: str | int,
        key_number: int,
        api_key: str,
    ) -> bool:

        clean_key = api_key.strip()

        if not clean_key:
            raise ValueError(
                "API Key نمی‌تواند خالی باشد."
            )

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return False

        result = await self.db.execute(
            f"""
            UPDATE {self.KEY_TABLE}
            SET
                api_key = ?,
                status = 'AVAILABLE',
                status_reason = NULL,
                cooldown_until = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE provider_id = ?
              AND key_number = ?
            """,
            (
                clean_key,
                int(provider_row["id"]),
                int(key_number),
            ),
        )

        return result.rowcount > 0

    async def delete_api_key(
        self,
        provider: str | int,
        key_number: int,
    ) -> bool:

        provider_row = await self.get(
            provider
        )

        if provider_row is None:
            return False

        result = await self.db.execute(
            f"""
            DELETE FROM {self.KEY_TABLE}
            WHERE provider_id = ?
              AND key_number = ?
            """,
            (
                int(provider_row["id"]),
                int(key_number),
            ),
        )

        return result.rowcount > 0

