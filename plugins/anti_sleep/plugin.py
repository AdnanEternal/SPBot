import asyncio
import random
import re
import time

import aiohttp

from core.base_plugin import BasePlugin
from core.time_manager import now

from . import handlers
from .store import AntiSleepStore
from plugins.system_plugin.github_manager.manager import (
    GitHubManager,
)


class AntiSleepPlugin(BasePlugin):
    name = "Anti Sleep"
    version = "1.1.0"

    MIN_INTERVAL_SECONDS = 60
    MAX_INTERVAL_SECONDS = 15 * 60

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
        self._chat_entity = None

    async def _resolve_chat_entity(
        self,
        chat_id: int,
    ):
        try:
            dialogs = await self.client.get_dialogs()

        except Exception as exc:
            print(
                "⚠️ Anti Sleep - "
                f"دریافت لیست گروه‌ها ناموفق بود: "
                f"chat_id={chat_id} "
                f"type={type(exc).__name__} "
                f"error={exc}"
            )
            return None

        for dialog in dialogs:
            if dialog.id == int(chat_id):
                return dialog.entity

        print(
            "⚠️ Anti Sleep - "
            f"گروه در dialogs پیدا نشد: chat_id={chat_id}"
        )

        return None

    @staticmethod
    def _format_github_error(
        exc: Exception,
    ) -> str:
        error_text = str(exc).strip()

        match = re.search(
            r"GitHub connection failed:\s*(\d{3})",
            error_text,
        )

        if match:
            return f"HTTP {match.group(1)}"

        if isinstance(
            exc,
            asyncio.TimeoutError,
        ):
            return "Timeout"

        if isinstance(
            exc,
            aiohttp.ClientConnectionError,
        ):
            return "Connection error"

        if isinstance(
            exc,
            aiohttp.ClientError,
        ):
            return "Network error"

        if error_text:
            return error_text[:120]

        return type(exc).__name__

    async def _ping_github(self) -> str:
        started_at = time.perf_counter()

        try:
            github = GitHubManager()

            await github.check_connection()

            elapsed = (
                time.perf_counter()
                - started_at
            )

            return (
                "✅ موفق "
                f"(HTTP 200، {elapsed:.2f}s)"
            )

        except asyncio.TimeoutError:
            elapsed = (
                time.perf_counter()
                - started_at
            )

            return (
                "⏱️ بدون پاسخ "
                f"(Timeout، {elapsed:.2f}s)"
            )

        except Exception as exc:
            elapsed = (
                time.perf_counter()
                - started_at
            )

            error = self._format_github_error(
                exc
            )

            return (
                f"❌ ناموفق "
                f"({error}، {elapsed:.2f}s)"
            )

    async def on_load(self) -> None:
        await self.store.create_table()

    async def on_enable(self) -> None:
        settings = await self.store.get()

        if (
            settings["enabled"]
            and settings["chat_id"] is not None
        ):
            self._chat_entity = (
                await self._resolve_chat_entity(
                    int(settings["chat_id"])
                )
            )

            await self.start_heartbeat()

    async def on_disable(self) -> None:
        await self.stop_heartbeat()
        self._chat_entity = None

    async def start_heartbeat(self) -> None:
        if (
            self._heartbeat_task is not None
            and not self._heartbeat_task.done()
        ):
            return

        self._heartbeat_task = (
            asyncio.create_task(
                self._heartbeat_loop()
            )
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

                # فاصله‌ی کاملاً تصادفی بین 1 تا 15 دقیقه
                delay_seconds = random.uniform(
                    self.MIN_INTERVAL_SECONDS,
                    self.MAX_INTERVAL_SECONDS,
                )

                delay_minutes = (
                    delay_seconds / 60
                )

                print(
                    "💓 Anti Sleep - "
                    f"heartbeat بعد از "
                    f"{delay_minutes:.2f} دقیقه"
                )

                await asyncio.sleep(
                    delay_seconds
                )

                # ممکن است هنگام sleep سیستم غیرفعال شده باشد
                settings = await self.store.get()

                if (
                    not settings["enabled"]
                    or settings["chat_id"] is None
                ):
                    return

                chat_id = int(
                    settings["chat_id"]
                )

                chat = self._chat_entity

                if chat is None:
                    chat = (
                        await self._resolve_chat_entity(
                            chat_id
                        )
                    )

                    if chat is None:
                        await asyncio.sleep(30)
                        continue

                    self._chat_entity = chat

                # مهم:
                # حتی در صورت Timeout یا هر خطای دیگر
                # _ping_github همیشه یک نتیجه برمی‌گرداند.
                github_result = (
                    await self._ping_github()
                )

                timestamp = now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                message = (
                    "💓 Anti Sleep Heartbeat\n"
                    f"🕒 {timestamp}\n"
                    f"🔗 GitHub: {github_result}"
                )

                # ارسال heartbeat مستقل از نتیجه GitHub
                try:
                    await self.client.send_message(
                        chat,
                        message,
                    )

                except Exception as exc:
                    # احتمال stale شدن entity گروه
                    self._chat_entity = None

                    print(
                        "⚠️ Anti Sleep - "
                        f"ارسال heartbeat ناموفق بود: "
                        f"{exc}"
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

                # یک خطای داخلی نباید task را بکشد
                await asyncio.sleep(30)

    enable_anti_sleep = (
        handlers.enable_anti_sleep
    )