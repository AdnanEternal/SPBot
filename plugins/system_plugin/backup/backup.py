import os
import sqlite3
import tempfile

from config import config
from core.database_manager import DatabaseManager
from ..github_manager.manager import GitHubManager


class DatabaseBackupManager:
    def __init__(
        self,
        db: DatabaseManager,
        github: GitHubManager,
    ):
        self.db = db
        self.github = github

        self.remote_path = config.get(
            "GITHUB_DATABASE_BACKUP_PATH",
            "backups/latest.db",
        )

    async def create_backup(self) -> None:
        if self.db.connection is None:
            raise RuntimeError("Database is not connected")

        file_descriptor, temp_path = tempfile.mkstemp(
            suffix=".db",
            prefix="database_backup_",
        )

        os.close(file_descriptor)

        try:
            target = sqlite3.connect(temp_path)

            try:
                await self.db.connection.backup(target)
            finally:
                target.close()

            await self.github.upload_file(
                local_path=temp_path,
                remote_path=self.remote_path,
                commit_message="Update database backup",
            )

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def restore_backup(self) -> None:
        if self.db.connection is None:
            raise RuntimeError("Database is not connected")

        db_path = self.db.db_path

        file_descriptor, temp_path = tempfile.mkstemp(
            suffix=".db",
            prefix="database_restore_",
            dir=os.path.dirname(db_path) or ".",
        )

        os.close(file_descriptor)

        old_path = f"{db_path}.restore_old"

        try:
            # دانلود بکاپ از GitHub
            await self.github.download_file(
                remote_path=self.remote_path,
                local_path=temp_path,
            )

            # بررسی سلامت فایل SQLite
            connection = sqlite3.connect(temp_path)

            try:
                result = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()

                if not result or result[0] != "ok":
                    raise RuntimeError(
                        "Downloaded database failed integrity check"
                    )
            finally:
                connection.close()

            # اطمینان از ثبت کامل WAL قبل از بستن دیتابیس
            await self.db.connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            )

            await self.db.close()

            wal_path = f"{db_path}-wal"
            shm_path = f"{db_path}-shm"

            # دیتابیس قبلی را نگه می‌داریم تا اگر restore شکست خورد
            # بتوانیم برش گردانیم.
            if os.path.exists(old_path):
                os.remove(old_path)

            os.replace(db_path, old_path)

            if os.path.exists(wal_path):
                os.remove(wal_path)

            if os.path.exists(shm_path):
                os.remove(shm_path)

            try:
                os.replace(temp_path, db_path)

                # دوباره دیتابیس جدید را متصل کن
                await self.db.connect()

            except Exception:
                # اگر اتصال دیتابیس جدید شکست خورد، قبلی را برگردان
                if self.db.connection is not None:
                    await self.db.close()

                if os.path.exists(db_path):
                    os.remove(db_path)

                os.replace(old_path, db_path)

                await self.db.connect()

                raise

            # restore موفق بود
            if os.path.exists(old_path):
                os.remove(old_path)

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

            if os.path.exists(old_path):
                os.remove(old_path)