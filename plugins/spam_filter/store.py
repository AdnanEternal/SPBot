from typing import Any

from core.database_manager import DatabaseManager
from core.ttl_cache import TTLCache


DEFAULT_FLOOD_COUNT = 5
DEFAULT_FLOOD_SECONDS = 10
DEFAULT_MAX_LINKS = 3
DEFAULT_MAX_REPEAT = 3


class SpamSettingsStore:
    TABLE = "spam_settings"

    CACHE_MAX_GROUPS = 512
    CACHE_TTL_SECONDS = 900

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

        self._cache = TTLCache[
            int,
            dict[str, Any],
        ](
            max_entries=self.CACHE_MAX_GROUPS,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": "INTEGER PRIMARY KEY",
                "flood_count": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_FLOOD_COUNT}"
                ),
                "flood_seconds": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_FLOOD_SECONDS}"
                ),
                # برای سازگاری با دیتابیس‌های قبلی
                "max_links": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_MAX_LINKS}"
                ),
                "max_repeat": (
                    f"INTEGER NOT NULL "
                    f"DEFAULT {DEFAULT_MAX_REPEAT}"
                ),
            },
        )

    async def _ensure_row(
        self,
        group_id: int,
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
            },
            or_ignore=True,
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

        await self._ensure_row(group_id)

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

    async def set_flood(
        self,
        group_id: int,
        count: int,
        seconds: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "flood_count": count,
                "flood_seconds": seconds,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(group_id)

        if cached is not None:
            cached["flood_count"] = count
            cached["flood_seconds"] = seconds

            self._cache.set(
                group_id,
                cached,
            )

    async def set_max_repeat(
        self,
        group_id: int,
        count: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "max_repeat": count,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(group_id)

        if cached is not None:
            cached["max_repeat"] = count

            self._cache.set(
                group_id,
                cached,
            )


class SpamWhitelistStore:
    TABLE = "spam_whitelist"

    CACHE_MAX_GROUPS = 512
    CACHE_TTL_SECONDS = 900

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

        self._cache = TTLCache[
            int,
            set[int],
        ](
            max_entries=self.CACHE_MAX_GROUPS,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                ),
                "group_id": (
                    "INTEGER NOT NULL"
                ),
                "user_id": (
                    "INTEGER NOT NULL"
                ),
            },
            indexes=[
                "group_id",
                "user_id",
            ],
        )

    async def _load_group(
        self,
        group_id: int,
    ) -> set[int]:
        cached = self._cache.get(group_id)

        if cached is not None:
            return set(cached)

        rows = await self.db.select_all(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        users = {
            int(row["user_id"])
            for row in rows
        }

        self._cache.set(
            group_id,
            users,
        )

        return set(users)

    async def is_exempt(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        users = await self._load_group(group_id)
        return user_id in users

    async def add(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        users = await self._load_group(group_id)

        if user_id in users:
            return False

        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
            },
        )

        users.add(user_id)

        self._cache.set(
            group_id,
            users,
        )

        return True

    async def remove(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        users = await self._load_group(group_id)

        if user_id not in users:
            return False

        await self.db.execute(
            f"""
            DELETE FROM {self.TABLE}
            WHERE group_id = ?
              AND user_id = ?
            """,
            (
                group_id,
                user_id,
            ),
        )

        users.discard(user_id)

        self._cache.set(
            group_id,
            users,
        )

        return True

    async def get_all(
        self,
        group_id: int,
    ) -> list[int]:
        users = await self._load_group(group_id)
        return sorted(users)


class SpamContextStore:
    TABLE = "spam_user_context"

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                ),
                "group_id": (
                    "INTEGER NOT NULL"
                ),
                "user_id": (
                    "INTEGER NOT NULL"
                ),
                "joined_at": (
                    "REAL"
                ),
                "first_seen_at": (
                    "REAL"
                ),
            },
            unique=[
                (
                    "group_id",
                    "user_id",
                )
            ],
            indexes=[
                "group_id",
                "user_id",
            ],
        )

        try:
            columns = await self.db.fetchall(
                f"PRAGMA table_info({self.TABLE})"
            )

            names = {
                row[1]
                for row in columns
            }

            if "first_seen_at" not in names:
                await self.db.execute(
                    f"""
                    ALTER TABLE {self.TABLE}
                    ADD COLUMN first_seen_at REAL
                    """
                )

        except Exception as exc:
            print(
                f"⚠️ migration جدول "
                f"{self.TABLE} ناموفق بود: {exc}"
            )

    async def ensure_first_seen(
        self,
        group_id: int,
        user_id: int,
        seen_at: float,
    ) -> None:
        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
        )

        if row is None:
            await self.db.insert(
                self.TABLE,
                {
                    "group_id": group_id,
                    "user_id": user_id,
                    "first_seen_at": seen_at,
                },
            )
            return

        if row["first_seen_at"] is None:
            first_seen = (
                row["joined_at"]
                if row["joined_at"] is not None
                else seen_at
            )

            await self.db.update(
                self.TABLE,
                {
                    "first_seen_at": first_seen,
                },
                where={
                    "group_id": group_id,
                    "user_id": user_id,
                },
            )

    async def set_joined_at(
        self,
        group_id: int,
        user_id: int,
        joined_at: float,
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
                "joined_at": joined_at,
                "first_seen_at": joined_at,
            },
            or_ignore=True,
        )

        await self.db.update(
            self.TABLE,
            {
                "joined_at": joined_at,
            },
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
        )

    async def get_reference_time(
        self,
        group_id: int,
        user_id: int,
    ) -> float | None:
        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
        )

        if not row:
            return None

        if row["joined_at"] is not None:
            return float(
                row["joined_at"]
            )

        if row["first_seen_at"] is not None:
            return float(
                row["first_seen_at"]
            )

        return None

    async def clear_user(
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


class SpamRuleStore:
    """
    Rule Engine عمومی Spam Filter.

    text_forbidden:
        عبارت ممنوع

    text_allowed:
        استثنا

    اگر occurrence یک قانون ممنوع با occurrence
    یک قانون مجاز overlap داشته باشد، همان occurrence
    از قانون ممنوع مستثنی می‌شود.
    """

    TABLE = "spam_custom_rules"

    CACHE_MAX_GROUPS = 256
    CACHE_TTL_SECONDS = 900

    def __init__(
        self,
        db: DatabaseManager,
    ) -> None:
        self.db = db

        self._cache = TTLCache[
            int,
            list[dict[str, Any]],
        ](
            max_entries=self.CACHE_MAX_GROUPS,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

    async def create_table(self) -> None:
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                ),
                "group_id": (
                    "INTEGER NOT NULL"
                ),
                "rule_type": (
                    "TEXT NOT NULL"
                ),
                "pattern": (
                    "TEXT NOT NULL"
                ),
                "action": (
                    "TEXT NOT NULL"
                ),
            },
            unique=[
                (
                    "group_id",
                    "rule_type",
                    "pattern",
                )
            ],
            indexes=[
                "group_id",
            ],
        )

    async def get_all(
        self,
        group_id: int,
    ) -> list[dict[str, Any]]:
        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            return [
                dict(item)
                for item in cached
            ]

        rows = await self.db.select_all(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        rules = [
            dict(row)
            for row in rows
        ]

        self._cache.set(
            group_id,
            rules,
        )

        return [
            dict(item)
            for item in rules
        ]

    async def _add_rule(
        self,
        group_id: int,
        rule_type: str,
        pattern: str,
    ) -> bool:
        pattern = pattern.strip()

        if not pattern:
            return False

        pattern = pattern.casefold()

        if rule_type not in (
            "text_forbidden",
            "text_allowed",
        ):
            raise ValueError(
                f"Unknown rule type: {rule_type}"
            )

        result = await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "rule_type": rule_type,
                "pattern": pattern,
                "action": (
                    "hard_spam"
                    if rule_type == "text_forbidden"
                    else "allow"
                ),
            },
            or_ignore=True,
        )

        self._cache.delete(
            group_id
        )

        return result.rowcount > 0

    async def add_forbidden(
        self,
        group_id: int,
        pattern: str,
    ) -> bool:
        return await self._add_rule(
            group_id,
            "text_forbidden",
            pattern,
        )

    async def add_allowed(
        self,
        group_id: int,
        pattern: str,
    ) -> bool:
        return await self._add_rule(
            group_id,
            "text_allowed",
            pattern,
        )

    async def _remove_rule(
        self,
        group_id: int,
        rule_type: str,
        pattern: str,
    ) -> bool:
        pattern = pattern.strip().casefold()

        if not pattern:
            return False

        result = await self.db.delete(
            self.TABLE,
            {
                "group_id": group_id,
                "rule_type": rule_type,
                "pattern": pattern,
            },
        )

        self._cache.delete(
            group_id
        )

        return result.rowcount > 0

    async def remove_forbidden(
        self,
        group_id: int,
        pattern: str,
    ) -> bool:
        return await self._remove_rule(
            group_id,
            "text_forbidden",
            pattern,
        )

    async def remove_allowed(
        self,
        group_id: int,
        pattern: str,
    ) -> bool:
        return await self._remove_rule(
            group_id,
            "text_allowed",
            pattern,
        )

    async def has_forbidden(
        self,
        group_id: int,
    ) -> bool:
        rules = await self.get_all(
            group_id
        )

        return any(
            rule["rule_type"]
            == "text_forbidden"
            for rule in rules
        )

    @staticmethod
    def _find_occurrences(
        text: str,
        pattern: str,
    ) -> list[tuple[int, int]]:
        result = []

        start = 0

        while True:
            index = text.find(
                pattern,
                start,
            )

            if index == -1:
                break

            result.append(
                (
                    index,
                    index + len(pattern),
                )
            )

            start = index + 1

        return result

    @staticmethod
    def _overlaps(
        a_start: int,
        a_end: int,
        b_start: int,
        b_end: int,
    ) -> bool:
        return (
            a_start < b_end
            and b_start < a_end
        )

    async def match_texts(
        self,
        group_id: int,
        texts: list[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        rules = await self.get_all(
            group_id
        )

        forbidden_rules = [
            rule
            for rule in rules
            if rule["rule_type"]
            == "text_forbidden"
        ]

        allowed_rules = [
            rule
            for rule in rules
            if rule["rule_type"]
            == "text_allowed"
        ]

        if not forbidden_rules:
            return []

        matches = []

        for source, raw_text in texts:
            if not raw_text:
                continue

            text = raw_text.casefold()

            allowed_occurrences = []

            for rule in allowed_rules:
                pattern = (
                    str(rule["pattern"])
                    .casefold()
                )

                for start, end in (
                    self._find_occurrences(
                        text,
                        pattern,
                    )
                ):
                    allowed_occurrences.append(
                        (
                            start,
                            end,
                            pattern,
                        )
                    )

            for rule in forbidden_rules:
                pattern = (
                    str(rule["pattern"])
                    .casefold()
                )

                occurrences = (
                    self._find_occurrences(
                        text,
                        pattern,
                    )
                )

                for start, end in occurrences:
                    exempted = any(
                        self._overlaps(
                            start,
                            end,
                            allowed_start,
                            allowed_end,
                        )
                        for (
                            allowed_start,
                            allowed_end,
                            _,
                        ) in allowed_occurrences
                    )

                    if exempted:
                        continue

                    matches.append(
                        {
                            "rule_id": rule["id"],
                            "pattern": rule["pattern"],
                            "source": source,
                            "action": rule["action"],
                        }
                    )

                    # برای یک متن یک بار کافی است.
                    break

        return matches