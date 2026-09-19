import asyncio
import os
import re
from pathlib import Path
from typing import NamedTuple, Optional


import aiosqlite

from config import config

class ExecuteResult(NamedTuple):
    rowcount: int
    lastrowid: int | None


_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)


def _validate_identifier(name: str) -> str:
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"❌ نام نامعتبر برای جدول/فیلد: '{name}'"
        )
    return name


class DatabaseManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = (
            db_path
            or config.get(
                "DB_PATH",
                "data/bot.db",
            )
        )

        self.connection: Optional[
            aiosqlite.Connection
        ] = None

        # برای جلوگیری از تداخل عملیات عادی دیتابیس
        # با backup/restore
        self.maintenance_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._connect_lock:
            if self.connection is not None:
                return

            db_path = Path(self.db_path)

            db_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            restore_old = Path(
                f"{self.db_path}.restore_old"
            )

            if (
                not db_path.exists()
                and restore_old.exists()
            ):
                print(
                    "♻️ دیتابیس اصلی پیدا نشد؛ "
                    "در حال بازیابی نسخه‌ی rollback..."
                )

                os.replace(
                    restore_old,
                    db_path,
                )

            connection = None

            try:
                connection = await aiosqlite.connect(
                    self.db_path
                )

                connection.row_factory = aiosqlite.Row

                await connection.execute(
                    "PRAGMA foreign_keys=ON"
                )

                await connection.execute(
                    "PRAGMA busy_timeout=10000"
                )

                try:
                    await connection.execute(
                        "PRAGMA journal_mode=WAL"
                    )

                except Exception as exc:
                    print(
                        "⚠️ فعال‌سازی WAL ناموفق بود؛ "
                        "SQLite با journal معمولی اجرا می‌شود."
                    )
                    print(exc)

                    await connection.execute(
                        "PRAGMA journal_mode=DELETE"
                    )

                await connection.execute(
                    "PRAGMA synchronous=NORMAL"
                )

                await connection.commit()

                self.connection = connection

                print("✅ دیتابیس متصل شد.")

            except Exception:
                if connection is not None:
                    try:
                        await connection.close()
                    except Exception:
                        pass

                self.connection = None
                raise
    async def close(self):
        async with self.maintenance_lock:
            if self.connection is not None:
                await self.connection.close()
                self.connection = None

                print(
                    "🔌 اتصال دیتابیس بسته شد."
                )

    async def execute(
        self,
        query: str,
        params: tuple = (),
) -> ExecuteResult:
        async with self.maintenance_lock:
            if self.connection is None:
                raise RuntimeError(
                    "Database connection is not available"
                )

            cursor = None

            try:
                cursor = await self.connection.execute(
                    query,
                    params,
                )

                await self.connection.commit()

                return ExecuteResult(
                    rowcount=cursor.rowcount,
                    lastrowid=cursor.lastrowid,
                )

            except Exception:
                try:
                    await self.connection.rollback()
                except Exception:
                    pass

                raise

            finally:
                if cursor is not None:
                    await cursor.close()    
    async def fetchone(
        self,
        query: str,
        params: tuple = (),
    ):
        async with self.maintenance_lock:
            if self.connection is None:
                raise RuntimeError(
                    "Database connection is not available"
                )

            cursor = await self.connection.execute(
                query,
                params,
            )

            try:
                return await cursor.fetchone()
            finally:
                await cursor.close()

    async def fetchall(
        self,
        query: str,
        params: tuple = (),
    ):
        async with self.maintenance_lock:
            if self.connection is None:
                raise RuntimeError(
                    "Database connection is not available"
                )

            cursor = await self.connection.execute(
                query,
                params,
            )

            try:
                return await cursor.fetchall()
            finally:
                await cursor.close()

    async def create_table(
        self,
        table_name: str,
        columns: dict,
        unique: Optional[list] = None,
        indexes: Optional[list] = None,
    ):
        _validate_identifier(table_name)

        col_defs = []

        for col_name, col_type in columns.items():
            _validate_identifier(col_name)

            col_defs.append(
                f"{col_name} {col_type}"
            )

        if unique:
            for cols in unique:
                for col_name in cols:
                    _validate_identifier(col_name)

                col_defs.append(
                    f"UNIQUE({', '.join(cols)})"
                )

        query = (
            f"CREATE TABLE IF NOT EXISTS "
            f"{table_name} "
            f"({', '.join(col_defs)})"
        )

        await self.execute(query)

        for col_name in indexes or []:
            _validate_identifier(col_name)

            await self.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"idx_{table_name}_{col_name} "
                f"ON {table_name} ({col_name})"
            )

    async def insert(
        self,
        table_name: str,
        values: dict,
        or_ignore: bool = False,
    ):
        _validate_identifier(table_name)

        columns = list(values.keys())

        for col_name in columns:
            _validate_identifier(col_name)

        placeholders = ", ".join(
            ["?"] * len(columns)
        )

        or_clause = (
            "OR IGNORE "
            if or_ignore
            else ""
        )

        query = (
            f"INSERT {or_clause}"
            f"INTO {table_name} "
            f"({', '.join(columns)}) "
            f"VALUES ({placeholders})"
        )

        return await self.execute(
            query,
            tuple(values.values()),
        )

    async def update(
        self,
        table_name: str,
        values: dict,
        where: dict,
    ):
        _validate_identifier(table_name)

        set_cols = list(values.keys())
        where_cols = list(where.keys())

        for col_name in (
            set_cols + where_cols
        ):
            _validate_identifier(col_name)

        set_clause = ", ".join(
            f"{c} = ?"
            for c in set_cols
        )

        where_clause = " AND ".join(
            f"{c} = ?"
            for c in where_cols
        )

        query = (
            f"UPDATE {table_name} "
            f"SET {set_clause} "
            f"WHERE {where_clause}"
        )

        params = (
            tuple(values.values())
            + tuple(where.values())
        )

        return await self.execute(
            query,
            params,
        )

    async def delete(
        self,
        table_name: str,
        where: dict,
    ):
        _validate_identifier(table_name)

        where_cols = list(where.keys())

        for col_name in where_cols:
            _validate_identifier(col_name)

        where_clause = " AND ".join(
            f"{c} = ?"
            for c in where_cols
        )

        query = (
            f"DELETE FROM {table_name} "
            f"WHERE {where_clause}"
        )

        return await self.execute(
            query,
            tuple(where.values()),
        )

    async def select_one(
        self,
        table_name: str,
        where: Optional[dict] = None,
        columns: str = "*",
    ):
        query, params = self._build_select(
            table_name,
            where,
            columns,
        )

        return await self.fetchone(
            query,
            params,
        )

    async def select_all(
        self,
        table_name: str,
        where: Optional[dict] = None,
        columns: str = "*",
    ):
        query, params = self._build_select(
            table_name,
            where,
            columns,
        )

        return await self.fetchall(
            query,
            params,
        )

    def _build_select(
        self,
        table_name: str,
        where: Optional[dict],
        columns: str,
    ):
        _validate_identifier(table_name)

        query = (
            f"SELECT {columns} "
            f"FROM {table_name}"
        )

        params: tuple = ()

        if where:
            where_cols = list(where.keys())

            for col_name in where_cols:
                _validate_identifier(col_name)

            query += (
                " WHERE "
                + " AND ".join(
                    f"{c} = ?"
                    for c in where_cols
                )
            )

            params = tuple(
                where.values()
            )

        return query, params