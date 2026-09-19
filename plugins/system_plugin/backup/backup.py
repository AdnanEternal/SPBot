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

    async def _acquire_maintenance_lock(self) -> None:
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
    def _check_sqlite_integrity(path: str) -> None:
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
        file_descriptor = None
        temp_path = None

        try:
            file_descriptor, temp_path = tempfile.mkstemp(
                suffix=".db",
                prefix="database_backup_",
            )

            os.close(file_descriptor)
            file_descriptor = None

            # فقط مرحله‌ی snapshot دیتابیس قفل می‌شود.
            await self._acquire_maintenance_lock()

            try:
                if self.db.connection is None:
                    raise RuntimeError(
                        "اتصال دیتابیس برقرار نیست."
                    )

                print("💾 ساخت backup دیتابیس...")

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

            finally:
                self.db.maintenance_lock.release()

            # از اینجا به بعد DB آزاد است.
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

            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    async def restore_backup(self) -> None:
        file_descriptor = None
        temp_path = None
        lock_acquired = False

        db_path = self.db.db_path
        old_path = f"{db_path}.restore_old"

        had_existing_db = False

        try:
            # اول backup را دانلود می‌کنیم؛ بدون قفل DB.
            file_descriptor, temp_path = tempfile.mkstemp(
                suffix=".db",
                prefix="database_restore_",
                dir=(
                    os.path.dirname(db_path)
                    or "."
                ),
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

            # فقط از اینجا به بعد DB قفل می‌شود.
            await self._acquire_maintenance_lock()
            lock_acquired = True

            had_existing_db = os.path.exists(
                db_path
            )

            if self.db.connection is not None:
                await self.db.connection.close()
                self.db.connection = None

            # rollback قبلی را پاک می‌کنیم.
            if os.path.exists(old_path):
                os.remove(old_path)

            # دیتابیس فعلی را نگه می‌داریم.
            if had_existing_db:
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

            # backup جدید را نصب می‌کنیم.
            os.replace(
                temp_path,
                db_path,
            )

            temp_path = None

            print(
                "♻️ اتصال به دیتابیس بازیابی‌شده..."
            )

            await self.db.connect()

            await asyncio.to_thread(
                self._check_sqlite_integrity,
                db_path,
            )

            if os.path.exists(old_path):
                os.remove(old_path)

            print(
                "✅ دیتابیس با موفقیت بازیابی شد."
            )

        except Exception:
            print(
                "❌ Restore شکست خورد؛ "
                "در حال تلاش برای rollback..."
            )

            try:
                if self.db.connection is not None:
                    await self.db.connection.close()
                    self.db.connection = None
            except Exception:
                pass

            try:
                if os.path.exists(db_path):
                    os.remove(db_path)
            except Exception:
                pass

            # rollback فقط در صورتی که DB قبلی داشتیم.
            if (
                had_existing_db
                and os.path.exists(old_path)
            ):
                try:
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

            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            if lock_acquired:
                self.db.maintenance_lock.release()