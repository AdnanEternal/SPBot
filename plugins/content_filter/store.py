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

        self._cache = TTLCache[int, set[str]](
            max_entries=self.CACHE_MAX_GROUPS,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

    async def create_table(self):
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "group_id": "INTEGER NOT NULL",
                "word": "TEXT NOT NULL",
            },
            unique=[("group_id", "word")],
            indexes=["group_id"],
        )

    async def add(
        self,
        group_id: int,
        word: str,
    ):
        word = word.lower().strip()

        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "word": word,
            },
            or_ignore=True,
        )

        # اگر این گروه از قبل cache شده،
        # همان cache را هم بلافاصله به‌روزرسانی کن.
        cached = self._cache.get(group_id)

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
        word = word.lower().strip()

        cursor = await self.db.delete(
            self.TABLE,
            {
                "group_id": group_id,
                "word": word,
            },
        )

        removed = cursor.rowcount > 0

        if removed:
            cached = self._cache.get(group_id)

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
        """
        مهم‌ترین مسیر:

        اگر گروه در cache باشد:
            DB اصلاً صدا زده نمی‌شود.

        اگر نباشد:
            فقط یک بار DB خوانده می‌شود
            و نتیجه در RAM قرار می‌گیرد.
        """

        words = await self.get_all(group_id)

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
        # اول RAM
        cached = self._cache.get(group_id)

        if cached is not None:
            return set(cached)

        # فقط در cache miss سراغ DB
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