class ViolationStore:
    TABLE = "violations"

    def __init__(self, db):
        self.db = db

    async def create_table(self):
        await self.db.create_table(
            self.TABLE,
            columns={
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "group_id": "INTEGER NOT NULL",
                "user_id": "INTEGER NOT NULL",
                "reason": "TEXT NOT NULL",
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
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
        reason: str,
    ):
        await self.db.insert(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
                "reason": reason,
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

        return int(row["count"])


    async def get_users(self, group_id: int):
        rows = await self.db.fetchall(
            f"""
            SELECT user_id, COUNT(*) AS violation_count
            FROM {self.TABLE}
            WHERE group_id = ?
            GROUP BY user_id
            ORDER BY violation_count DESC
            """,
            (group_id,),
        )

        return rows


    async def get_all(
        self,
        group_id: int,
        user_id: int,
    ):
        return await self.db.select_all(
            self.TABLE,
            where={
                "group_id": group_id,
                "user_id": user_id,
            },
        )

    async def reset(
        self,
        group_id: int,
        user_id: int,
    ):
        await self.db.delete(
            self.TABLE,
            {
                "group_id": group_id,
                "user_id": user_id,
            },
        )

