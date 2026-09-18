class WordFilterStore:
    """
    لایه‌ی persistence فیلتر کلمات.
    هر کلمه مال یه گروه خاصه (group_id) و هیچ اشتراکی بین گروه‌ها نیست.
    """

    TABLE = "content_filter_words"

    def __init__(self, db):
        self.db = db

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

    async def add(self, group_id: int, word: str):
        word = word.lower().strip()

        await self.db.insert(
            self.TABLE,
            {"group_id": group_id, "word": word},
            or_ignore=True,
        )

    async def remove(self, group_id: int, word: str):
        word = word.lower().strip()

        cursor = await self.db.delete(
            self.TABLE,
            {
                "group_id": group_id,
                "word": word,
            },
        )

        return cursor.rowcount > 0

    async def find_match(self, group_id: int, text: str) -> str | None:
        """
        اگر متن شامل یکی از کلمات فیلترشده باشد،
        همان کلمه را برمی‌گرداند.
        در غیر این صورت None.
        """
        words = await self.get_all(group_id)
        text = text.lower()

        for word in words:
            if word in text:
                return word

        return None

    async def contains(self, group_id: int, text: str) -> bool:
        return await self.find_match(group_id, text) is not None

    async def get_all(self, group_id: int) -> set:
        rows = await self.db.select_all(
            self.TABLE,
            where={"group_id": group_id},
        )

        return {row["word"] for row in rows}