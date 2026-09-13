import re
from pathlib import Path
from typing import Optional

import aiosqlite

from config import config

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str) -> str:
    """
    اسم جدول/فیلد رو نمیشه parametrize کرد، پس حداقل مطمئن می‌شیم یه
    شناسه‌ی SQL معتبره (جلوگیری از inject شدن هرچیزی به‌عنوان اسم ستون/جدول).
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"❌ نام نامعتبر برای جدول/فیلد: '{name}'")
    return name


class DatabaseManager:
    """
    لایه‌ی دیتابیس. هیچ ایده‌ای از schema یا داده‌ی پلاگین‌ها نداره —
    این مسئولیت خود پلاگین‌هاست.

    هر پلاگین جدول‌های خودش رو با create_table می‌سازه و با
    insert/update/delete/select_one/select_all کار می‌کنه، بدون اینکه لازم
    باشه برای کارهای معمولی SQL خام بنویسه. برای query های خاص و پیچیده،
    execute/fetchone/fetchall همچنان در دسترسن.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.get("DB_PATH", "data/bot.db")
        self.connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row

        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.commit()

        print("✅ دیتابیس متصل شد.")

    async def close(self):
        if self.connection:
            await self.connection.close()
            print("🔌 اتصال دیتابیس بسته شد.")

    # ---------- لایه‌ی خام (برای query های خاص/پیچیده) ----------

    async def execute(self, query: str, params: tuple = ()):
        """برای INSERT / UPDATE / DELETE / CREATE TABLE. cursor رو برمی‌گردونه."""
        cursor = await self.connection.execute(query, params)
        await self.connection.commit()
        return cursor

    async def fetchone(self, query: str, params: tuple = ()):
        cursor = await self.connection.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    async def fetchall(self, query: str, params: tuple = ()):
        cursor = await self.connection.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

    # ---------- لایه‌ی ساده برای پلاگین‌ها (بدون نوشتن SQL خام) ----------

    async def create_table(
        self,
        table_name: str,
        columns: dict,
        unique: Optional[list] = None,
        indexes: Optional[list] = None,
    ):
        """
        مثال:
            await db.create_table(
                "content_filter_words",
                columns={
                    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "group_id": "INTEGER NOT NULL",
                    "word": "TEXT NOT NULL",
                },
                unique=[("group_id", "word")],
                indexes=["group_id"],
            )
        """
        _validate_identifier(table_name)

        col_defs = []
        for col_name, col_type in columns.items():
            _validate_identifier(col_name)
            col_defs.append(f"{col_name} {col_type}")

        if unique:
            for cols in unique:
                for col_name in cols:
                    _validate_identifier(col_name)
                col_defs.append(f"UNIQUE({', '.join(cols)})")

        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"
        await self.execute(query)

        for col_name in indexes or []:
            _validate_identifier(col_name)
            await self.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_{col_name} "
                f"ON {table_name} ({col_name})"
            )

    async def insert(self, table_name: str, values: dict, or_ignore: bool = False):
        """
        مثال:
            await db.insert(
                "content_filter_words",
                {"group_id": 123, "word": "spam"},
                or_ignore=True,
            )
        """
        _validate_identifier(table_name)
        columns = list(values.keys())
        for col_name in columns:
            _validate_identifier(col_name)

        placeholders = ", ".join(["?"] * len(columns))
        or_clause = "OR IGNORE " if or_ignore else ""
        query = (
            f"INSERT {or_clause}INTO {table_name} ({', '.join(columns)}) "
            f"VALUES ({placeholders})"
        )
        return await self.execute(query, tuple(values.values()))

    async def update(self, table_name: str, values: dict, where: dict):
        """
        مثال:
            await db.update("content_filter_words", {"word": "new"}, where={"id": 1})
        """
        _validate_identifier(table_name)
        set_cols = list(values.keys())
        where_cols = list(where.keys())
        for col_name in set_cols + where_cols:
            _validate_identifier(col_name)

        set_clause = ", ".join(f"{c} = ?" for c in set_cols)
        where_clause = " AND ".join(f"{c} = ?" for c in where_cols)
        query = f"UPDATE {table_name} SET {set_clause} WHERE {where_clause}"
        params = tuple(values.values()) + tuple(where.values())
        return await self.execute(query, params)

    async def delete(self, table_name: str, where: dict):
        """
        مثال:
            await db.delete("content_filter_words", {"group_id": 123, "word": "spam"})
        """
        _validate_identifier(table_name)
        where_cols = list(where.keys())
        for col_name in where_cols:
            _validate_identifier(col_name)

        where_clause = " AND ".join(f"{c} = ?" for c in where_cols)
        query = f"DELETE FROM {table_name} WHERE {where_clause}"
        return await self.execute(query, tuple(where.values()))

    async def select_one(self, table_name: str, where: Optional[dict] = None, columns: str = "*"):
        query, params = self._build_select(table_name, where, columns)
        return await self.fetchone(query, params)

    async def select_all(self, table_name: str, where: Optional[dict] = None, columns: str = "*"):
        query, params = self._build_select(table_name, where, columns)
        return await self.fetchall(query, params)

    def _build_select(self, table_name: str, where: Optional[dict], columns: str):
        _validate_identifier(table_name)
        query = f"SELECT {columns} FROM {table_name}"
        params: tuple = ()

        if where:
            where_cols = list(where.keys())
            for col_name in where_cols:
                _validate_identifier(col_name)
            query += " WHERE " + " AND ".join(f"{c} = ?" for c in where_cols)
            params = tuple(where.values())

        return query, params
