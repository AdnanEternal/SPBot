import asyncio

from splusthon import SoroushClient
from splusthon.sessions import StringSession


class ClientManager:
    START_TIMEOUT = 60
    STOP_TIMEOUT = 20

    def __init__(self, session_string: str | None = None):
        self.session_string = session_string

        if not self.session_string:
            raise ValueError(
                "❌ SESSION_STRING یافت نشد! "
                "لطفاً آن را در محیط سرور تنظیم کنید."
            )

        self.client: SoroushClient | None = None

    async def _disconnect_quietly(
        self,
        client: SoroushClient,
    ) -> None:
        try:
            await asyncio.wait_for(
                client.disconnect(),
                timeout=self.STOP_TIMEOUT,
            )
        except Exception:
            pass

    async def start(self):
        if self.client is not None:
            return self.client

        client = SoroushClient(
            StringSession(self.session_string)
        )

        self.client = client

        try:
            await asyncio.wait_for(
                client.start(),
                timeout=self.START_TIMEOUT,
            )

            print("✅ ربات به سروش متصل شد.")
            return client

        except asyncio.CancelledError:
            await self._disconnect_quietly(client)
            self.client = None
            raise

        except Exception as exc:
            print(
                f"❌ خطا در اتصال به سروش: {exc}"
            )

            await self._disconnect_quietly(client)
            self.client = None

            return None

    async def stop(self):
        """
        اتصال را به‌صورت امن و با timeout می‌بندد.
        """
        client = self.client
        self.client = None

        if client is None:
            return

        try:
            await asyncio.wait_for(
                client.disconnect(),
                timeout=self.STOP_TIMEOUT,
            )

            print("🔌 اتصال به سروش قطع شد.")

        except asyncio.TimeoutError:
            print(
                "⚠️ قطع اتصال سروش بیش از حد طول کشید."
            )

        except Exception as exc:
            print(
                f"⚠️ خطا هنگام قطع اتصال سروش: {exc}"
            )

    def get_client(self):
        return self.client