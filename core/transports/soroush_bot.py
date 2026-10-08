import re
import asyncio
import struct
from typing import Iterable
import aiohttp

from splusthon import SoroushClient
from splusthon.sessions import StringSession
from splusthon.tl.tlobject import TLRequest

from core.transport import BaseTransport


# =========================================================
# AUTH
# =========================================================


class ImportBotAuthorizationRequest(
    TLRequest
):
    """
    SPlusthon 1.1.4 این request را در generated auth module ندارد،
    بنابراین request را فقط در transport نگه می‌داریم.
    """

    CONSTRUCTOR_ID = 0x67A3FF2C

    def __init__(
        self,
        flags: int,
        api_id: int,
        api_hash: str,
        bot_auth_token: str,
    ) -> None:

        self.flags = int(flags)
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.bot_auth_token = bot_auth_token

    def to_dict(self):
        return {
            "_": "ImportBotAuthorizationRequest",
            "flags": self.flags,
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "bot_auth_token": self.bot_auth_token,
        }

    def _bytes(self):
        return b"".join(
            (
                b"\x2c\xff\xa3\x67",

                struct.pack(
                    "<i",
                    self.flags,
                ),

                struct.pack(
                    "<i",
                    self.api_id,
                ),

                self.serialize_bytes(
                    self.api_hash
                ),

                self.serialize_bytes(
                    self.bot_auth_token
                ),
            )
        )

    @classmethod
    def from_reader(cls, reader):
        return cls(
            flags=reader.read_int(),
            api_id=reader.read_int(),
            api_hash=reader.tgread_string(),
            bot_auth_token=reader.tgread_string(),
        )


# =========================================================
# TRANSPORT
# =========================================================


class SoroushBotTransport(
    BaseTransport
):
    """
    Soroush Standard Bot transport.

    Core و Pluginها فقط همان SoroushClient را می‌بینند.
    """
 
    command_prefix = "/"
    command_name_field = "native_name"
    command_display_backticks = False
    supports_inline_buttons = True

    START_TIMEOUT = 60
    REQUEST_TIMEOUT = 60
    STOP_TIMEOUT = 20

    def __init__(
        self,
        bot_token: str,
    ):

        bot_token = (
            bot_token or ""
        ).strip()

        if not bot_token:
            raise ValueError(
                "❌ BOT_TOKEN یافت نشد! "
                "لطفاً آن را در محیط سرور تنظیم کنید."
            )

        self.bot_token = bot_token
        self.client: SoroushClient | None = None
    
    # =========================================================
    # NATIVE COMMANDS
    # =========================================================

    async def sync_commands(
        self,
        commands: Iterable,
    ) -> None:
        """
        Native Command Menu را به وضعیت فعلی
        Command Registry همگام می‌کند.

        ابتدا وضعیت فعلی را از Soroush Bot API می‌گیرد.
        اگر با registry مطلوب یکسان باشد، هیچ درخواستی
        برای setMyCommands ارسال نمی‌شود.

        در صورت تفاوت، کل registry مطلوب یک‌جا اعمال می‌شود.
        """

        if not self.bot_token:
            raise RuntimeError(
                "BOT_TOKEN برای همگام‌سازی Native Command وجود ندارد."
            )

        payload_commands = []

        for command in commands:

            native_name = str(
                getattr(
                    command,
                    "native_name",
                    "",
                )
                or ""
            ).strip().lower()

            description = str(
                getattr(
                    command,
                    "description",
                    "",
                )
                or ""
            ).strip()

            if not native_name:
                continue

            # امنیت نهایی نزدیک API
            if not re.fullmatch(
                r"[a-z0-9_]{1,32}",
                native_name,
            ):
                print(
                    "⚠️ Native Command نامعتبر رد شد: "
                    f"{native_name!r}"
                )
                continue

            payload_commands.append(
                {
                    "command": native_name,
                    "description": (
                        description
                        or "بدون توضیح"
                    )[:256],
                }
            )

        url = (
            "https://api.splus.ir/bot"
            f"{self.bot_token}"
        )

        timeout = aiohttp.ClientTimeout(
            total=30
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            # =================================================
            # GET CURRENT NATIVE COMMANDS
            # =================================================

            async with session.get(
                f"{url}/getMyCommands",
            ) as response:

                response_text = (
                    await response.text()
                )

                if response.status != 200:
                    raise RuntimeError(
                        "Soroush Bot API HTTP "
                        f"{response.status}: "
                        f"{response_text}"
                    )

                try:

                    data = await response.json(
                        content_type=None
                    )

                except Exception as exc:

                    raise RuntimeError(
                        "پاسخ getMyCommands "
                        "JSON معتبر نبود: "
                        f"{response_text}"
                    ) from exc

                if not data.get(
                    "ok",
                    False,
                ):
                    raise RuntimeError(
                        "Soroush Bot API درخواست "
                        f"getMyCommands را رد کرد: "
                        f"{data}"
                    )

                current_commands = (
                    data.get(
                        "result",
                        [],
                    )
                )

                if not isinstance(
                    current_commands,
                    list,
                ):
                    raise RuntimeError(
                        "پاسخ getMyCommands یک "
                        "لیست معتبر نبود."
                    )

            # =================================================
            # NORMALIZE CURRENT STATE
            # =================================================

            current_normalized = []

            for command in current_commands:

                if not isinstance(
                    command,
                    dict,
                ):
                    continue

                current_name = str(
                    command.get(
                        "command",
                        "",
                    )
                    or ""
                ).strip().lower()

                current_description = str(
                    command.get(
                        "description",
                        "",
                    )
                    or ""
                ).strip()

                current_normalized.append(
                    {
                        "command": current_name,
                        "description": current_description,
                    }
                )

            # =================================================
            # NO CHANGE
            # =================================================

            if (
                current_normalized
                == payload_commands
            ):
                print(
                    "✅ Native Command registry "
                    "از قبل به‌روز است؛ "
                    "نیازی به sync نیست."
                )
                return

            # =================================================
            # APPLY NEW STATE
            # =================================================

            async with session.post(
                f"{url}/setMyCommands",
                json={
                    "commands": payload_commands,
                },
            ) as response:

                response_text = (
                    await response.text()
                )

                if response.status != 200:
                    raise RuntimeError(
                        "Soroush Bot API HTTP "
                        f"{response.status}: "
                        f"{response_text}"
                    )

                try:

                    data = await response.json(
                        content_type=None
                    )

                except Exception as exc:

                    raise RuntimeError(
                        "پاسخ setMyCommands "
                        "JSON معتبر نبود: "
                        f"{response_text}"
                    ) from exc

                if not data.get(
                    "ok",
                    False,
                ):
                    raise RuntimeError(
                        "Soroush Bot API درخواست "
                        f"setMyCommands را رد کرد: "
                        f"{data}"
                    )

        print(
            "✅ Native Command registry "
            "با موفقیت به‌روز شد. "
            f"تعداد: {len(payload_commands)}"
        )
        
    async def clear_commands(self) -> None:
        """
        Native Command List فعلی Standard Bot را پاک می‌کند.

        این متد فقط command registry مربوط به Native Menu را پاک می‌کند
        و هیچ چیزی از CommandManager یا Pluginها حذف نمی‌کند.
        """

        if not self.bot_token:
            raise RuntimeError(
                "BOT_TOKEN برای پاک‌کردن Native Command وجود ندارد."
            )

        url = (
            "https://api.splus.ir/bot"
            f"{self.bot_token}"
            "/deleteMyCommands"
        )

        timeout = aiohttp.ClientTimeout(
            total=30
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.post(
                url,
                json={},
            ) as response:

                response_text = (
                    await response.text()
                )

                if response.status != 200:
                    raise RuntimeError(
                        "Soroush Bot API HTTP "
                        f"{response.status}: "
                        f"{response_text}"
                    )

                try:
                    data = await response.json(
                        content_type=None
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "پاسخ Soroush Bot API "
                        "JSON معتبر نبود: "
                        f"{response_text}"
                    ) from exc

                if not data.get(
                    "ok",
                    False,
                ):
                    raise RuntimeError(
                        "Soroush Bot API درخواست "
                        f"deleteMyCommands را رد کرد: "
                        f"{data}"
                    )

        print(
            "🧹 Native Command List با موفقیت پاک شد."
        )
    # =========================================================
    # DISCONNECT
    # =========================================================

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

    # =========================================================
    # START
    # =========================================================

    async def start(self):

        if self.client is not None:
            return self.client

        client = SoroushClient(
            StringSession()
        )

        self.client = client

        try:

            # -------------------------------------------------
            # CONNECTION
            # -------------------------------------------------

            await asyncio.wait_for(
                client.connect(),
                timeout=self.START_TIMEOUT,
            )

            # -------------------------------------------------
            # BOT AUTH
            # -------------------------------------------------

            result = await asyncio.wait_for(

                client(
                    ImportBotAuthorizationRequest(
                        flags=0,
                        api_id=client.api_id,
                        api_hash=client.api_hash,
                        bot_auth_token=self.bot_token,
                    )
                ),

                timeout=self.REQUEST_TIMEOUT,
            )

            user = getattr(
                result,
                "user",
                None,
            )

            if user is None:

                raise RuntimeError(
                    "SPlusthon پاسخ احراز هویت ربات را "
                    "بدون user برگرداند."
                )

            await asyncio.wait_for(
                client._on_login(user),
                timeout=self.REQUEST_TIMEOUT,
            )

            print(
                "✅ ربات استاندارد سروش متصل شد."
            )

            return client

        except asyncio.CancelledError:

            await self._disconnect_quietly(
                client
            )

            self.client = None

            raise

        except Exception as exc:

            print(
                "❌ خطا در اتصال ربات استاندارد سروش: "
                f"{exc}"
            )

            await self._disconnect_quietly(
                client
            )

            self.client = None

            return None

    # =========================================================
    # STOP
    # =========================================================

    async def stop(self) -> None:

        client = self.client
        self.client = None

        if client is None:
            return

        try:

            result = client.disconnect()

            if asyncio.iscoroutine(result):

                await asyncio.wait_for(
                    result,
                    timeout=self.STOP_TIMEOUT,
                )

            print(
                "🔌 اتصال ربات استاندارد سروش قطع شد."
            )

        except asyncio.TimeoutError:

            print(
                "⚠️ قطع اتصال ربات استاندارد سروش "
                "بیش از حد طول کشید."
            )

        except Exception as exc:

            print(
                "⚠️ خطا هنگام قطع اتصال ربات استاندارد سروش: "
                f"{exc}"
            )

    def get_client(self):
        return self.client