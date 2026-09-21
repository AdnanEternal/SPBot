import asyncio
import signal
import time
import traceback

from config import config
from core.client import ClientManager
from core.plugin_manager import PluginManager


async def run_bot(
    shutdown_event: asyncio.Event,
) -> bool:
    """
    خروجی:
        True  -> shutdown عمدی
        False -> اتصال قطع شده و باید reconnect شود
    """

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

        done, pending = await asyncio.wait(
    {
        run_task,
        shutdown_task,
    },
    return_when=asyncio.FIRST_COMPLETED,
)

        for task in pending:
            task.cancel()

        if pending:
            await asyncio.gather(
                *pending,
                return_exceptions=True,
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


async def async_main() -> None:
    delay = 5

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

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
            pass

    try:
        while not shutdown_event.is_set():
            started = time.monotonic()

            try:
                should_exit = await run_bot(
                    shutdown_event
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

            if shutdown_event.is_set():
                break

            print(
                f"⏳ تلاش بعدی برای اجرا تا "
                f"{delay} ثانیه دیگر..."
            )

            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=delay,
                )
            except asyncio.TimeoutError:
                pass

    finally:
        for sig in signal_handlers:
            try:
                loop.remove_signal_handler(sig)
            except Exception:
                pass


def main() -> None:
    asyncio.run(async_main())


main()