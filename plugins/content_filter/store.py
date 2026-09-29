from core.ttl_cache import TTLCache


class WordFilterStore:
    """
    لایه‌ی persistence فیلتر کلمات.

    برای سرعت، لیست کلمات گروه‌ها به‌صورت محدود و موقت
    در RAM cache می‌شود.

    Cache:
    - حداکثر 128 گروه
    - TTL = 10 دقیقه
    """

    TABLE = "content_filter_words"

    CACHE_MAX_GROUPS = 128
    CACHE_TTL_SECONDS = 600

    def __init__(self, db):
        self.db = db

        self._cache = TTLCache[
            int,
            set[str],
        ](
            max_entries=self.CACHE_MAX_GROUPS,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

    async def create_table(self):
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                ),
                "group_id": (
                    "INTEGER NOT NULL"
                ),
                "word": (
                    "TEXT NOT NULL"
                ),
            },
            unique=[
                (
                    "group_id",
                    "word",
                )
            ],
            indexes=[
                "group_id",
            ],
        )

    async def add(
        self,
        group_id: int,
        word: str,
    ):
        word = (
            word.lower()
            .strip()
        )

        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "word": word,
            },
            or_ignore=True,
        )

        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            cached.add(word)

            self._cache.set(
                group_id,
                cached,
            )

    async def remove(
        self,
        group_id: int,
        word: str,
    ):
        word = (
            word.lower()
            .strip()
        )

        cursor = await self.db.delete(
            self.TABLE,
            {
                "group_id": group_id,
                "word": word,
            },
        )

        removed = (
            cursor.rowcount > 0
        )

        if removed:
            cached = self._cache.get(
                group_id
            )

            if cached is not None:
                cached.discard(word)

                self._cache.set(
                    group_id,
                    cached,
                )

        return removed

    async def find_match(
        self,
        group_id: int,
        text: str,
    ) -> str | None:
        words = await self.get_all(
            group_id
        )

        if not words:
            return None

        text = text.lower()

        for word in words:

            if word in text:
                return word

        return None

    async def contains(
        self,
        group_id: int,
        text: str,
    ) -> bool:
        return (
            await self.find_match(
                group_id,
                text,
            )
            is not None
        )

    async def get_all(
        self,
        group_id: int,
    ) -> set[str]:
        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            return set(cached)

        rows = await self.db.select_all(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        words = {
            row["word"]
            for row in rows
        }

        self._cache.set(
            group_id,
            words,
        )

        return set(words)


class ContentFilterSettingsStore:
    TABLE = "content_filter_settings"

    # پیش‌فرض:
    # ادمین‌ها مشمول فیلتر نیستند
    DEFAULT_ADMINS_ALLOWED = True

    def __init__(self, db):
        self.db = db

        self._cache = TTLCache[
            int,
            bool,
        ](
            max_entries=256,
            ttl_seconds=900,
        )

    async def create_table(self):
        await self.db.create_table(
            self.TABLE,
            columns={
                "group_id": (
                    "INTEGER PRIMARY KEY"
                ),
                "admins_allowed": (
                    "INTEGER NOT NULL "
                    f"DEFAULT {int(self.DEFAULT_ADMINS_ALLOWED)}"
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
                "admins_allowed": int(
                    self.DEFAULT_ADMINS_ALLOWED
                ),
            },
            or_ignore=True,
        )

    async def get_admins_allowed(
        self,
        group_id: int,
    ) -> bool:
        cached = self._cache.get(
            group_id
        )

        if cached is not None:
            return bool(cached)

        await self._ensure_row(
            group_id
        )

        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
            },
        )

        allowed = bool(
            int(
                row["admins_allowed"]
            )
        )

        self._cache.set(
            group_id,
            allowed,
        )

        return allowed

    async def set_admins_allowed(
        self,
        group_id: int,
        allowed: bool,
    ) -> None:
        await self._ensure_row(
            group_id
        )

        value = (
            1
            if allowed
            else 0
        )

        await self.db.update(
            self.TABLE,
            {
                "admins_allowed": value,
            },
            where={
                "group_id": group_id,
            },
        )

        self._cache.set(
            group_id,
            bool(allowed),
        )


class ContentFilterViolationStore:
    """
    سابقه‌ی اختصاصی استفاده از کلمات فیلترشده.

    این سابقه کاملاً متعلق به Content Filter است
    و وارد Violation Manager نمی‌شود.
    """

    TABLE = "content_filter_violations"

    def __init__(self, db):
        self.db = db

    async def create_table(self):
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
                "word": (
                    "TEXT NOT NULL"
                ),
                "created_at": (
                    "TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                ),
            },
            indexes=[
                "group_id",
                "user_id",
            ],
        )

    async def add(
        self,
        group_id: int,
        user_id: int,
        word: str,
    ) -> None:
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
                "word": word,
            },
        )

    async def get_count(
        self,
        group_id: int,
        user_id: int,
    ) -> int:
        row = await self.db.select_one(
            self.TABLE,
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
            columns="COUNT(*) AS count",
        )

        return int(
            row["count"]
        )