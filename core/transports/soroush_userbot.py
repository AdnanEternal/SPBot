import asyncio
from typing import Iterable


from splusthon import SoroushClient
from splusthon.sessions import StringSession

from config import config
from core.transport import BaseTransport
from core.transports.soroush_worker_connection import (
    SoroushWorkerClient,
    is_soroush_proxy_enabled,
)


class SoroushUserbotTransport(
    BaseTransport
):
    command_prefix = "!"
    command_name_field = "name"
    command_display_backticks = True

    supports_inline_buttons = False

    START_TIMEOUT = 60
    STOP_TIMEOUT = 20

    def __init__(
        self,
        session_string: str,
    ):
        session_string = (
            session_string or ""
        ).strip()

        if not session_string:
            raise ValueError(
                "❌ SESSION_STRING یافت نشد! "
                "لطفاً آن را در محیط سرور تنظیم کنید."
            )

        self.session_string = session_string
        self.client: SoroushClient | None = None

    async def _disconnect_quietly(
        self,
        client: SoroushClient,
    ) -> None:
        try:
            result = client.disconnect()

            if asyncio.iscoroutine(result):
                await asyncio.wait_for(
                    result,
                    timeout=self.STOP_TIMEOUT,
                )

        except Exception:
            pass

    async def start(self):

        if self.client is not None:
            return self.client

        client = None

        try:
            session = StringSession(self.session_string)

            if is_soroush_proxy_enabled():
                client = SoroushWorkerClient(session)
                print(
                    "🌐 اتصال سروش از طریق Cloudflare Worker فعال است."
                )
            else:
                client = SoroushClient(session)
                print(
                    "🌐 اتصال سروش مستقیم است؛ پروکسی غیرفعال است."
                )

            self.client = client

            await asyncio.wait_for(
                client.start(),
                timeout=self.START_TIMEOUT,
            )

            print(
                "✅ ربات به سروش متصل شد."
            )

            return client

        except asyncio.CancelledError:

            if client is not None:
                await self._disconnect_quietly(
                    client
                )

            self.client = None

            raise

        except Exception as exc:

            print(
                f"❌ خطا در اتصال به سروش: {exc}"
            )

            if client is not None:
                await self._disconnect_quietly(
                    client
                )

            self.client = None

            return None

    async def sync_commands(
        self,
        commands: Iterable,
    ) -> None:
        """
        UserBot Native Bot Command Menu ندارد.

        Registry در Core همچنان مشترک است،
        ولی این Transport برای این قابلیت کاری انجام نمی‌دهد.
        """
        return None

    async def clear_commands(self) -> None:
        """
        UserBot Native Command Menu ندارد.
        """
        return None

    async def stop(self) -> None:

        client = self.client
        self.client = None

        if client is None:
            return

        try:

            await asyncio.wait_for(
                client.disconnect(),
                timeout=self.STOP_TIMEOUT,
            )

            print(
                "🔌 اتصال سروش قطع شد."
            )

        except asyncio.TimeoutError:

            print(
                "⚠️ قطع اتصال سروش "
                "بیش از حد طول کشید."
            )

        except Exception as exc:

            print(
                "⚠️ خطا هنگام قطع اتصال سروش: "
                f"{exc}"
            )

    def get_client(self):
        return self.client
