import os
import sqlite3
import tempfile

from config import config
from core.database_manager import DatabaseManager
from github_manager.manager import GitHubManager


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