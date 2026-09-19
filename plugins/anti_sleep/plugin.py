import asyncio
from datetime import datetime

from core.base_plugin import BasePlugin

from . import handlers
from .store import AntiSleepStore
from plugins.system_plugin.github_manager.manager import (
    GitHubManager,
)


class AntiSleepPlugin(BasePlugin):
    name = "Anti Sleep"
    version = "1.0.0"

    def __init__(
        self,
        client,
        command_manager,
        db,
        event_bus,
    ):
        super().__init__(
            client,
            command_manager,
            db,
            event_bus,
        )

        self.store = AntiSleepStore(self.db)
        self._heartbeat_task: asyncio.Task | None = None

    async def on_load(self) -> None:
        await self.store.create_table()

    async def on_enable(self) -> None:
        settings = await self.store.get()

        if (
            settings["enabled"]
            and settings["chat_id"] is not None
        ):
            await self.start_heartbeat()

    async def on_disable(self) -> None:
        await self.stop_heartbeat()

    async def start_heartbeat(self) -> None:
        if (
            self._heartbeat_task is not None
            and not self._heartbeat_task.done()
        ):
            return

        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop()
        )

    async def stop_heartbeat(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None

        if task is None:
            return

        if not task.done():
            task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                settings = await self.store.get()

                if (
                    not settings["enabled"]
                    or settings["chat_id"] is None
                ):
                    return

                interval = max(
                    1,
                    int(settings["interval_minutes"]),
                )

                # اولین heartbeat بعد از فاصله‌ی تنظیم‌شده
                await asyncio.sleep(
                    interval * 60
                )

                settings = await self.store.get()

                if (
                    not settings["enabled"]
                    or settings["chat_id"] is None
                ):
                    return

                chat_id = int(
                    settings["chat_id"]
                )

                github_result = "❌ ناموفق"

                try:
                    github = GitHubManager()

                    await github.check_connection()

                    github_result = "✅ موفق"

                except Exception as exc:
                    print(
                        "⚠️ Anti Sleep - "
                        f"GitHub heartbeat failed: {exc}"
                    )

                timestamp = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                try:
                    await self.client.send_message(
                        chat_id,
                        (
                            "💓 Anti Sleep Heartbeat\n"
                            f"🕒 {timestamp}\n"
                            f"🔗 GitHub: {github_result}"
                        ),
                    )

                except Exception as exc:
                    print(
                        "⚠️ Anti Sleep - "
                        f"ارسال heartbeat ناموفق بود: {exc}"
                    )

            except asyncio.CancelledError:
                raise

            except Exception:
                import traceback

                print(
                    "❌ خطای غیرمنتظره در "
                    "Anti Sleep heartbeat:"
                )
                traceback.print_exc()

                # مهم: خطای یک heartbeat نباید
                # کل task را نابود کند.
                await asyncio.sleep(30)

    enable_anti_sleep = handlers.enable_anti_sleep