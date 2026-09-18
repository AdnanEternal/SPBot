import asyncio
import os
import sqlite3
import tempfile

from config import config
from core.database_manager import DatabaseManager
from ..github_manager.manager import GitHubManager


class DatabaseBackupManager:
    LOCK_TIMEOUT = 30
    INTEGRITY_TIMEOUT = 30

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

    async def _acquire_maintenance_lock(
        self,
    ):
        try:
            await asyncio.wait_for(
                self.db.maintenance_lock.acquire(),
                timeout=self.LOCK_TIMEOUT,
            )

        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                "دیتابیس در حال استفاده است و "
                "در مهلت تعیین‌شده آزاد نشد."
            ) from exc

    @staticmethod
    def _check_sqlite_integrity(
        path: str,
    ) -> None:
        connection = sqlite3.connect(
            path,
            timeout=30,
        )

        try:
            result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if (
                not result
                or result[0] != "ok"
            ):
                raise RuntimeError(
                    "فایل دیتابیس Integrity Check را رد کرد."
                )

        finally:
            connection.close()

    async def create_backup(self) -> None:
        await self._acquire_maintenance_lock()

        file_descriptor = None
        temp_path = None

        try:
            if self.db.connection is None:
                raise RuntimeError(
                    "اتصال دیتابیس برقرار نیست."
                )

            file_descriptor, temp_path = (
                tempfile.mkstemp(
                    suffix=".db",
                    prefix="database_backup_",
                )
            )

            os.close(file_descriptor)
            file_descriptor = None

            print(
                "💾 ساخت backup دیتابیس..."
            )

            target = sqlite3.connect(
                temp_path,
                timeout=30,
            )

            try:
                await self.db.connection.backup(
                    target
                )
            finally:
                target.close()

            await asyncio.to_thread(
                self._check_sqlite_integrity,
                temp_path,
            )

            print(
                "✅ Backup محلی سالم است؛ "
                "در حال آپلود به GitHub..."
            )

            await self.github.upload_file(
                local_path=temp_path,
                remote_path=self.remote_path,
                commit_message="Update database backup",
            )

            print(
                "✅ Backup دیتابیس با موفقیت ذخیره شد."
            )

        finally:
            if file_descriptor is not None:
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass

            if (
                temp_path
                and os.path.exists(temp_path)
            ):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            self.db.maintenance_lock.release()

    async def restore_backup(self) -> None:
        await self._acquire_maintenance_lock()

        file_descriptor = None
        temp_path = None

        db_path = self.db.db_path
        old_path = f"{db_path}.restore_old"

        restore_succeeded = False
        database_closed = False

        try:
            file_descriptor, temp_path = (
                tempfile.mkstemp(
                    suffix=".db",
                    prefix="database_restore_",
                    dir=(
                        os.path.dirname(db_path)
                        or "."
                    ),
                )
            )

            os.close(file_descriptor)
            file_descriptor = None

            print(
                "📥 دریافت backup از GitHub..."
            )

            await self.github.download_file(
                remote_path=self.remote_path,
                local_path=temp_path,
            )

            print(
                "🔎 بررسی سلامت backup..."
            )

            await asyncio.to_thread(
                self._check_sqlite_integrity,
                temp_path,
            )

            # دیتابیس فعلی را کامل می‌بندیم.
            if self.db.connection is not None:
                await self.db.connection.close()
                self.db.connection = None
                database_closed = True

            # اگر rollback قدیمی باقی مانده،
            # چون دیتابیس فعلی سالم و موجود است،
            # آن را نسخه‌ی stale فرض می‌کنیم.
            if os.path.exists(old_path):
                os.remove(old_path)

            # نسخه‌ی فعلی را نگه می‌داریم.
            if os.path.exists(db_path):
                os.replace(
                    db_path,
                    old_path,
                )

            wal_path = f"{db_path}-wal"
            shm_path = f"{db_path}-shm"

            if os.path.exists(wal_path):
                os.remove(wal_path)

            if os.path.exists(shm_path):
                os.remove(shm_path)

            # نصب backup جدید
            os.replace(
                temp_path,
                db_path,
            )

            temp_path = None

            print(
                "♻️ اتصال به دیتابیس بازیابی‌شده..."
            )

            await self.db.connect()

            # فایل جدید بعد از اتصال هم قابل استفاده است.
            await asyncio.to_thread(
                self._check_sqlite_integrity,
                db_path,
            )

            # restore کامل موفق بوده؛
            # حالا rollback قدیمی را حذف می‌کنیم.
            if os.path.exists(old_path):
                os.remove(old_path)

            restore_succeeded = True

            print(
                "✅ دیتابیس با موفقیت بازیابی شد."
            )

        except Exception:
            print(
                "❌ Restore شکست خورد؛ "
                "در حال تلاش برای rollback..."
            )

            # اتصال خراب/نیمه‌کاره را ببند.
            try:
                if self.db.connection is not None:
                    await self.db.connection.close()
                    self.db.connection = None
            except Exception:
                pass

            # اگر نسخه‌ی قبلی را داریم،
            # آن را برمی‌گردانیم.
            if os.path.exists(old_path):
                try:
                    if os.path.exists(db_path):
                        os.remove(db_path)

                    os.replace(
                        old_path,
                        db_path,
                    )

                    print(
                        "♻️ rollback موفق بود."
                    )

                except Exception as rollback_error:
                    print(
                        "🔥 rollback هم شکست خورد:"
                    )
                    print(
                        rollback_error
                    )

            # حتی اگر restore خراب شده،
            # تلاش می‌کنیم یک connection سالم
            # به دیتابیس فعلی داشته باشیم.
            try:
                if self.db.connection is None:
                    await self.db.connect()
            except Exception as reconnect_error:
                print(
                    "🔥 اتصال مجدد دیتابیس ممکن نشد:"
                )
                print(
                    reconnect_error
                )

            raise

        finally:
            if file_descriptor is not None:
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass

            if (
                temp_path
                and os.path.exists(temp_path)
            ):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            # عمداً اینجا old_path را حذف نمی‌کنیم.
            # فقط بعد از restore موفق حذف شده است.

            self.db.maintenance_lock.release()