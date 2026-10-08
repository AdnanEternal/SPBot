from config import config
from core.transport import BaseTransport
from core.transports.soroush_bot import SoroushBotTransport
from core.transports.soroush_userbot import SoroushUserbotTransport


class ClientManager:
    """
    Runtime boundary for Soroush authentication.

    The distinction between UserBot and Standard Bot is resolved here.
    main.py, Core services and plugins only receive the same SoroushClient.
    """

    def __init__(self):
        mode = (
            config.get("SPBOT_MODE", "")
            or ""
        ).strip().lower()

        session_string = (
            config.get("SESSION_STRING", "")
            or ""
        ).strip()

        bot_token = (
            config.get("BOT_TOKEN", "")
            or ""
        ).strip()

        # Explicit mode always wins.
        if mode in {"user", "userbot"}:
            self.transport: BaseTransport = (
                SoroushUserbotTransport(
                    session_string
                )
            )

        elif mode in {
            "bot",
            "standard",
            "standardbot",
        }:
            self.transport = (
                SoroushBotTransport(
                    bot_token
                )
            )

        elif mode in {"", "auto"}:
            # Auto mode is intentionally conservative:
            # if only one credential is present, use it.
            if session_string and not bot_token:
                self.transport = (
                    SoroushUserbotTransport(
                        session_string
                    )
                )

            elif bot_token and not session_string:
                self.transport = (
                    SoroushBotTransport(
                        bot_token
                    )
                )

            elif session_string and bot_token:
                raise ValueError(
                    "❌ هم SESSION_STRING و هم BOT_TOKEN تنظیم شده‌اند. "
                    "SPBOT_MODE را صریحاً روی userbot یا bot قرار دهید."
                )

            else:
                raise ValueError(
                    "❌ هیچ اعتبارنامه‌ای برای سروش تنظیم نشده است. "
                    "SESSION_STRING یا BOT_TOKEN را تنظیم کنید."
                )

        else:
            raise ValueError(
                "❌ SPBOT_MODE نامعتبر است. "
                "مقادیر مجاز: auto، userbot یا bot"
            )

    async def start(self):
        return await self.transport.start()

    async def stop(self):
        await self.transport.stop()

    def get_client(self):
        return self.transport.get_client()

    def get_transport(self) -> BaseTransport:
        return self.transport
