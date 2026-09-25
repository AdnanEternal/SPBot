import asyncio
import os
import sqlite3
import tempfile

from config import config
from core.database_manager import DatabaseManager
from ..github_manager.manager import GitHubManager
from core.time_manager import format_project_time, now_in

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
            timestamp = format_project_time(
                now_in("Asia/Tehran"),
                "%Y-%m-%d_%H-%M-%S",
            )

            archive_path = (
                f"backups/database_{timestamp}.db"
            )

            archive_path = (
                f"backups/database_{timestamp}.db"
            )

            await self.github.rotate_database_backup(
                local_path=temp_path,
                latest_path=self.remote_path,
                archive_path=archive_path,
                commit_message=(
                    f"Rotate database backup "
                    f"{timestamp}"
                ),
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

        # فایل‌های rollback
        old_db_path = f"{db_path}.restore_old"
        old_wal_path = f"{db_path}-wal.restore_old"
        old_shm_path = f"{db_path}-shm.restore_old"

        # فایل‌های جانبی دیتابیس فعال
        wal_path = f"{db_path}-wal"
        shm_path = f"{db_path}-shm"

        had_existing_db = False

        try:
            # -------------------------------------------------
            # 1. دریافت backup بدون قفل دیتابیس
            # -------------------------------------------------
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

            # -------------------------------------------------
            # 2. قفل دیتابیس
            # -------------------------------------------------
            await self._acquire_maintenance_lock()
            lock_acquired = True

            had_existing_db = os.path.exists(
                db_path
            )

            # -------------------------------------------------
            # 3. بستن اتصال فعلی
            # -------------------------------------------------
            if self.db.connection is not None:
                await self.db.connection.close()
                self.db.connection = None

            # -------------------------------------------------
            # 4. پاک کردن rollback قبلی
            # -------------------------------------------------
            for path in (
                old_db_path,
                old_wal_path,
                old_shm_path,
            ):
                if os.path.exists(path):
                    os.remove(path)

            # -------------------------------------------------
            # 5. ذخیره‌ی کامل دیتابیس فعلی برای rollback
            #
            # مهم:
            # اگر DB فعلی WAL/SHM داشته باشد،
            # آن‌ها هم باید همراه DB نگه داشته شوند.
            # -------------------------------------------------
            if had_existing_db:
                os.replace(
                    db_path,
                    old_db_path,
                )

                if os.path.exists(wal_path):
                    os.replace(
                        wal_path,
                        old_wal_path,
                    )

                if os.path.exists(shm_path):
                    os.replace(
                        shm_path,
                        old_shm_path,
                    )

            else:
                # اگر DB اصلی وجود ندارد، sidecarهای سرگردان
                # هم نباید وارد restore جدید شوند.
                for path in (
                    wal_path,
                    shm_path,
                ):
                    if os.path.exists(path):
                        os.remove(path)

            # -------------------------------------------------
            # 6. نصب backup جدید
            # -------------------------------------------------
            os.replace(
                temp_path,
                db_path,
            )

            temp_path = None

            # backup جدید نباید sidecar قدیمی داشته باشد.
            for path in (
                wal_path,
                shm_path,
            ):
                if os.path.exists(path):
                    os.remove(path)

            print(
                "♻️ اتصال به دیتابیس بازیابی‌شده..."
            )

            await self.db.connect()

            # -------------------------------------------------
            # 7. restore موفق بود؛ rollback backupهای قدیمی
            # دیگر لازم نیست.
            # -------------------------------------------------
            for path in (
                old_db_path,
                old_wal_path,
                old_shm_path,
            ):
                if os.path.exists(path):
                    os.remove(path)

            print(
                "✅ دیتابیس با موفقیت بازیابی شد."
            )

        except Exception:
            print(
                "❌ Restore شکست خورد؛ "
                "در حال تلاش برای rollback..."
            )

            # -------------------------------------------------
            # 8. بستن DB جدید
            # -------------------------------------------------
            try:
                if self.db.connection is not None:
                    await self.db.connection.close()
                    self.db.connection = None
            except Exception:
                pass

            # -------------------------------------------------
            # 9. حذف کامل DB جدید + WAL/SHM آن
            # -------------------------------------------------
            for path in (
                db_path,
                wal_path,
                shm_path,
            ):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as cleanup_error:
                    print(
                        f"⚠️ حذف فایل '{path}' ناموفق بود: "
                        f"{cleanup_error}"
                    )

            # -------------------------------------------------
            # 10. برگرداندن دیتابیس قبلی + WAL/SHM آن
            # -------------------------------------------------
            if had_existing_db:
                try:
                    if os.path.exists(old_db_path):
                        os.replace(
                            old_db_path,
                            db_path,
                        )

                    if os.path.exists(old_wal_path):
                        os.replace(
                            old_wal_path,
                            wal_path,
                        )

                    if os.path.exists(old_shm_path):
                        os.replace(
                            old_shm_path,
                            shm_path,
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

            else:
                print(
                    "⚠️ دیتابیس قبلی وجود نداشت؛ "
                    "نسخه‌ی restore‌شده حذف نشد."
                )

            # -------------------------------------------------
            # 11. اتصال مجدد
            # -------------------------------------------------
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