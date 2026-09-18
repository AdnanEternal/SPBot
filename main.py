

import asyncio
import traceback
import time

from config import config
from core.client import ClientManager
from core.plugin_manager import PluginManager


async def run_bot() -> None:
    session_string = config.get_required(
        "SESSION_STRING"
    )

    client_manager = ClientManager(
        session_string=session_string
    )

    client = None
    plugin_manager = None

    try:
        client = await client_manager.start()

        if not client:
            raise RuntimeError(
                "اتصال به Soroush برقرار نشد."
            )

        plugin_manager = PluginManager(client)

        await plugin_manager.load_all_plugins()
        await plugin_manager.enable_all_plugins()

        print(
            "✅ ربات با موفقیت اجرا شد."
        )
        print(
            "⏳ ربات در حال انتظار برای رویدادهاست..."
        )

        await client.run_until_disconnected()

    finally:
        if plugin_manager is not None:
            try:
                await plugin_manager.disable_all_plugins()
            except Exception:
                traceback.print_exc()

            try:
                await plugin_manager.db.close()
            except Exception:
                traceback.print_exc()

        if client_manager is not None:
            try:
                await client_manager.stop()
            except Exception:
                traceback.print_exc()


def main() -> None:
    delay = 5
    while True:
        started = time.monotonic()
        try:
            asyncio.run(run_bot())

        except KeyboardInterrupt:
            
            break

        except Exception:
           
            traceback.print_exc()

            print(
                "♻️ راه‌اندازی مجدد ربات..."
            )

        delay = 5 if time.monotonic() - started > 60 else min(delay * 2, 300)
        time.sleep(delay)

main()