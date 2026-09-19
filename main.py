import asyncio
import signal
import time
import traceback

from config import config
from core.client import ClientManager
from core.plugin_manager import PluginManager


async def run_bot() -> bool:
    """
    خروجی:
        True  -> shutdown عمدی، برنامه باید تمام شود.
        False -> اتصال قطع شده، main دوباره تلاش می‌کند.
    """

    session_string = config.get_required(
        "SESSION_STRING"
    )

    client_manager = ClientManager(
        session_string=session_string
    )

    client = None
    plugin_manager = None

    loop = asyncio.get_running_loop()

    shutdown_event = asyncio.Event()
    signal_handlers = []

    def request_shutdown() -> None:
        if not shutdown_event.is_set():
            print(
                "🛑 درخواست shutdown دریافت شد."
            )
            shutdown_event.set()

    for sig in (
        signal.SIGINT,
        signal.SIGTERM,
    ):
        try:
            loop.add_signal_handler(
                sig,
                request_shutdown,
            )
            signal_handlers.append(sig)

        except (
            NotImplementedError,
            RuntimeError,
            ValueError,
        ):
            # روی بعضی محیط‌ها signal handler پشتیبانی نمی‌شود.
            pass

    try:
        client = await client_manager.start()

        if not client:
            raise RuntimeError(
                "اتصال به Soroush برقرار نشد."
            )

        plugin_manager = PluginManager(
            client
        )

        await plugin_manager.load_all_plugins()
        await plugin_manager.enable_all_plugins()

        print(
            "✅ ربات با موفقیت اجرا شد."
        )
        print(
            "⏳ ربات در حال انتظار برای رویدادهاست..."
        )

        run_task = asyncio.create_task(
            client.run_until_disconnected()
        )

        shutdown_task = asyncio.create_task(
            shutdown_event.wait()
        )

        done, _ = await asyncio.wait(
            {
                run_task,
                shutdown_task,
            },
            return_when=asyncio.FIRST_COMPLETED,
        )

        if shutdown_task in done:
            print(
                "🔌 در حال خاموش‌سازی امن ربات..."
            )

            try:
                await client.disconnect()
            except Exception:
                traceback.print_exc()

            if not run_task.done():
                run_task.cancel()

            try:
                await run_task
            except BaseException:
                pass

            return True

        # اتصال خودش قطع شده.
        await run_task

        return False

    finally:
        for sig in signal_handlers:
            try:
                loop.remove_signal_handler(sig)
            except Exception:
                pass

        if plugin_manager is not None:
            try:
                await plugin_manager.disable_all_plugins()
            except Exception:
                traceback.print_exc()

            try:
                await plugin_manager.db.close()
            except Exception:
                traceback.print_exc()

        try:
            await client_manager.stop()
        except Exception:
            traceback.print_exc()


def main() -> None:
    delay = 5

    while True:
        started = time.monotonic()

        try:
            should_exit = asyncio.run(
                run_bot()
            )

            if should_exit:
                print(
                    "👋 ربات به‌صورت امن خاموش شد."
                )
                break

        except KeyboardInterrupt:
            print(
                "👋 ربات متوقف شد."
            )
            break

        except Exception:
            traceback.print_exc()

            print(
                "♻️ راه‌اندازی مجدد ربات..."
            )

        delay = (
            5
            if time.monotonic() - started > 60
            else min(
                delay * 2,
                300,
            )
        )

        print(
            f"⏳ تلاش بعدی برای اجرا تا {delay} ثانیه دیگر..."
        )

        time.sleep(delay)


main()