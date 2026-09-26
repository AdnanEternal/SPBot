from typing import Any

from core.database_manager import DatabaseManager
from core.ttl_cache import TTLCache


DEFAULT_FLOOD_COUNT = 5
DEFAULT_FLOOD_SECONDS = 10
DEFAULT_MAX_LINKS = 3
DEFAULT_MAX_REPEAT = 3


class SpamSettingsStore:
    """
    تنظیمات فیلتر اسپم هر گروه.
    """

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
        cached = self._cache.get(group_id)

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

    async def set_max_links(
        self,
        group_id: int,
        count: int,
    ) -> None:
        await self._ensure_row(group_id)

        await self.db.update(
            self.TABLE,
            {
                "max_links": count,
            },
            where={
                "group_id": group_id,
            },
        )

        cached = self._cache.get(group_id)

        if cached is not None:
            cached["max_links"] = count

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
    """
    کاربرانی که Spam Filter باید کاملاً نادیده‌شان بگیرد.

    whitelist فقط مربوط به Spam Filter است و روی
    content_filter / violation_manager تأثیری ندارد.

    برای مسیر عادی تشخیص اسپم، اطلاعات از RAM خوانده می‌شوند
    و SQLite فقط هنگام cache miss یا تغییر whitelist استفاده می‌شود.
    """

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
    """
    اطلاعات persistent مربوط به حضور کاربران در گروه.

    joined_at:
        زمان واقعی ورود، اگر Spam Filter آن را دیده باشد.

    first_seen_at:
        اولین زمانی که Spam Filter از کاربر پیامی دیده است.
        اگر joined_at ناشناخته باشد، این مقدار مبنای عمر کاربر است.
    """

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

        # برای دیتابیس‌های قدیمی که joined_at دارند
        # ولی first_seen_at را ندارند.
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
                f"⚠️ بررسی/migration جدول "
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

        # دیتابیس قدیمی:
        # اگر first_seen نداریم ولی joined_at داریم،
        # همان joined_at مبنای اولیه باشد.
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
    قوانین سفارشی Spam Filter.

    فعلاً فقط قانون:
        bio_contains

    action:
        hard_spam
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

    async def has_bio_rules(
        self,
        group_id: int,
    ) -> bool:
        rules = await self.get_all(
            group_id
        )

        return any(
            rule["rule_type"]
            == "bio_contains"
            for rule in rules
        )

    async def add_bio_rule(
        self,
        group_id: int,
        pattern: str,
    ) -> bool:
        pattern = pattern.strip()

        if not pattern:
            return False

        result = await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "rule_type": "bio_contains",
                "pattern": pattern,
                "action": "hard_spam",
            },
            or_ignore=True,
        )

        self._cache.delete(
            group_id
        )

        return result.rowcount > 0

    async def remove_bio_rule(
        self,
        group_id: int,
        pattern: str,
    ) -> bool:
        result = await self.db.delete(
            self.TABLE,
            {
                "group_id": group_id,
                "rule_type": "bio_contains",
                "pattern": pattern.strip(),
            },
        )

        self._cache.delete(
            group_id
        )

        return result.rowcount > 0

    async def match_bio(
        self,
        group_id: int,
        bio_text: str,
    ) -> list[dict[str, Any]]:
        rules = await self.get_all(
            group_id
        )

        if not bio_text:
            return []

        haystack = bio_text.casefold()

        matched = []

        for rule in rules:
            if (
                rule["rule_type"]
                != "bio_contains"
            ):
                continue

            pattern = (
                str(rule["pattern"])
                .casefold()
            )

            if (
                pattern
                and pattern in haystack
            ):
                matched.append(
                    rule
                )

        return matched