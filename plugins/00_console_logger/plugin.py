import asyncio
from pathlib import Path

from core.base_plugin import BasePlugin


class ConsoleLogger(BasePlugin):
    name = "Console Logger"
    version = "1.0.1"
    startup_priority = -1000

    async def on_startup(self):
        """
        تست مستقیم ارتباط StackHost با GitHub.

        این مرحله قبل از on_load و enable شدن پلاگین‌ها اجرا می‌شود.
        اگر آپلود موفق باشد، فایل logs/stackhost_github_test.txt
        روی GitHub ساخته یا به‌روزرسانی می‌شود.
        """

        test_path = Path(
            "data/stackhost_github_test.txt"
        )

        try:
            test_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            await asyncio.to_thread(
                test_path.write_text,
                "سلام دنیا",
                encoding="utf-8",
            )

            from plugins.system_plugin.github_manager.manager import (
                GitHubManager,
            )

            github = GitHubManager()

            await github.upload_file(
                local_path=str(test_path),
                remote_path="logs/stackhost_github_test.txt",
                commit_message=(
                    "test: StackHost GitHub connection"
                ),
            )

            print(
                "✅ Console Logger: "
                "ارتباط با GitHub موفق بود و "
                "فایل تست ساخته/به‌روزرسانی شد."
            )

        except Exception as exc:
            print(
                "❌ Console Logger: "
                "ارتباط با GitHub ناموفق بود: "
                f"{type(exc).__name__}: {exc}"
            )

        finally:
            try:
                test_path.unlink(
                    missing_ok=True
                )
            except Exception:
                pass