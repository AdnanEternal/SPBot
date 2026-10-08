# core/ui.py

import secrets
import time
import traceback
from dataclasses import dataclass
from typing import Any

import struct

from splusthon import events
from splusthon.tl import types
from splusthon.tl.tlobject import TLRequest
from splusthon.events import StopPropagation

from core.command_manager import CommandManager
from core.transport import BaseTransport


# =========================================================
# DATA
# =========================================================
class SetBotCallbackAnswerRequest(
    TLRequest
):
    """
    workaround برای SPlusthon 1.1.4

    خود TL schema متد messages.setBotCallbackAnswer
    را دارد، اما generated functions نسخه 1.1.4
    کلاس SetBotCallbackAnswerRequest را ندارد.
    """

    CONSTRUCTOR_ID = 0xD58F130A

    def __init__(
        self,
        *,
        query_id: int,
        cache_time: int = 0,
        alert: bool = False,
        message: str | None = None,
        url: str | None = None,
    ) -> None:

        flags = 0

        if message is not None:
            flags |= 1 << 0

        if alert:
            flags |= 1 << 1

        if url is not None:
            flags |= 1 << 2

        self.flags = flags
        self.query_id = int(query_id)
        self.message = message
        self.url = url
        self.cache_time = int(cache_time)

    def to_dict(self):
        return {
            "_": "SetBotCallbackAnswerRequest",
            "flags": self.flags,
            "query_id": self.query_id,
            "message": self.message,
            "alert": bool(
                self.flags & (1 << 1)
            ),
            "url": self.url,
            "cache_time": self.cache_time,
        }

    def _bytes(self):
        parts = [
            struct.pack(
                "<I",
                self.CONSTRUCTOR_ID,
            ),
            struct.pack(
                "<i",
                self.flags,
            ),
            struct.pack(
                "<q",
                self.query_id,
            ),
        ]

        if self.flags & (1 << 0):
            parts.append(
                self.serialize_bytes(
                    self.message
                )
            )

        if self.flags & (1 << 2):
            parts.append(
                self.serialize_bytes(
                    self.url
                )
            )

        parts.append(
            struct.pack(
                "<i",
                self.cache_time,
            )
        )

        return b"".join(parts)

    @classmethod
    def from_reader(
        cls,
        reader,
    ):
        flags = reader.read_int()

        query_id = reader.read_long()

        message = None

        if flags & (1 << 0):
            message = reader.tgread_string()

        url = None

        if flags & (1 << 2):
            url = reader.tgread_string()

        cache_time = reader.read_int()

        return cls(
            query_id=query_id,
            cache_time=cache_time,
            alert=bool(
                flags & (1 << 1)
            ),
            message=message,
            url=url,
        )

@dataclass(frozen=True)
class UICommandButton:
    """
    یک دکمه که در نهایت یک Command را با arguments اجرا می‌کند.
    """

    label: str
    command: Any
    args_text: str = ""


@dataclass(frozen=True)
class UIMarkup:
    """
    ساختار مستقل از Transport برای دکمه‌ها.
    """

    rows: tuple[
        tuple[UICommandButton, ...],
        ...,
    ]


@dataclass
class _CallbackAction:
    command_name: str
    args_text: str
    created_at: float


# =========================================================
# MANAGER
# =========================================================


class UIManager:
    """
    لایه‌ی عمومی UI/Interaction برای Pluginها.

    Plugin نباید بداند:
        - UserBot است یا Standard Bot
        - Button.inline چیست
        - CallbackQuery چیست
        - callback data چگونه ساخته می‌شود

    Plugin فقط UI مورد نظرش را تعریف می‌کند.
    """

    CALLBACK_PREFIX = b"spui:"
    CALLBACK_TTL = 3600
    MAX_CALLBACKS = 512

    def __init__(
        self,
        client,
        transport: BaseTransport,
        command_manager: CommandManager,
    ) -> None:

        self.client = client
        self.transport = transport
        self.command_manager = command_manager

        self._callbacks: dict[
            str,
            _CallbackAction,
        ] = {}

        # Callback فقط در Transportهایی که
        # واقعاً Inline Button دارند ثبت می‌شود.
        if getattr(
            transport,
            "supports_inline_buttons",
            False,
        ):
            self._register_callback_dispatcher()

    # =========================================================
    # PUBLIC API
    # =========================================================

    def command(
        self,
        label: str,
        command_or_name,
        args_text: str = "",
    ) -> UICommandButton:
        """
        ساخت یک دکمه‌ی منطقی برای اجرای Command.
        """

        return UICommandButton(
            label=str(label),
            command=command_or_name,
            args_text=str(args_text or "").strip(),
        )

    def row(
        self,
        *buttons: UICommandButton,
    ) -> tuple[UICommandButton, ...]:
        """
        ساخت یک ردیف دکمه.
        """

        return tuple(buttons)

    def markup(
        self,
        *rows: tuple[UICommandButton, ...],
    ) -> UIMarkup:
        """
        ساخت Markup مستقل از Transport.
        """

        return UIMarkup(
            rows=tuple(rows),
        )

    def pagination(
        self,
        command_or_name,
        current: int,
        total: int,
    ) -> UIMarkup | None:
        """
        Pagination عمومی.

        UserBot:
            متن command

        Standard Bot:
            Inline Buttons
        """

        current = int(current)
        total = int(total)

        if total <= 1:
            return None

        buttons: list[
            UICommandButton
        ] = []

        if current > 1:

            buttons.append(
                self.command(
                    f"« صفحه {current - 1}",
                    command_or_name,
                    str(current - 1),
                )
            )

        if current < total:

            buttons.append(
                self.command(
                    f"صفحه {current + 1} »",
                    command_or_name,
                    str(current + 1),
                )
            )

        if not buttons:
            return None

        return self.markup(
            self.row(*buttons)
        )

    # =========================================================
    # SEND
    # =========================================================

    async def reply(
        self,
        event,
        text: str,
        *,
        controls: UIMarkup | None = None,
        **kwargs,
    ):
        """
        ارسال یا ویرایش پیام با توجه به نوع Event و Transport.
        """

        # -------------------------------------------------
        # USERBOT FALLBACK
        # -------------------------------------------------

        if (
            controls is not None
            and not getattr(
                self.transport,
                "supports_inline_buttons",
                False,
            )
        ):

            text = self._append_text_controls(
                text,
                controls,
                event,
            )

            controls = None

        # -------------------------------------------------
        # STANDARD BOT
        # -------------------------------------------------

        buttons = (
            self._render_buttons(
                controls
            )
            if controls is not None
            else None
        )

        # -------------------------------------------------
        # CALLBACK -> EDIT
        # -------------------------------------------------

        if isinstance(
            event,
            events.CallbackQuery.Event,
        ):

            chat = await event.get_input_chat()

            result = await self.client.edit_message(
                chat,
                event.message_id,
                text,
                buttons=buttons,
                **kwargs,
            )

            return result

        # -------------------------------------------------
        # NORMAL MESSAGE -> REPLY
        # -------------------------------------------------

        return await event.reply(
            text,
            buttons=buttons,
            **kwargs,
        )

    # =========================================================
    # TEXT FALLBACK
    # =========================================================

    def _append_text_controls(
        self,
        text: str,
        controls: UIMarkup,
        event,
    ) -> str:

        lines = []

        for row in controls.rows:

            for button in row:

                usage = (
                    self.command_manager
                    .format_command(
                        button.command,
                        button.args_text,
                        event=event,
                    )
                )

                lines.append(
                    f"{button.label}: {usage}"
                )

        if not lines:
            return text

        return (
            f"{text}\n\n"
            + "\n".join(lines)
        )

    # =========================================================
    # STANDARD BUTTON RENDERER
    # =========================================================

    def _render_buttons(
        self,
        controls: UIMarkup,
    ):

        rendered_rows = []

        for row in controls.rows:

            rendered_buttons = []

            for button in row:

                command = (
                    self.command_manager
                    .resolve_command(
                        button.command
                    )
                )

                if command is None:
                    raise ValueError(
                        "کامند مربوط به UI Button "
                        "در registry پیدا نشد: "
                        f"{button.command!r}"
                    )

                token = (
                    self._create_callback(
                        command,
                        button.args_text,
                    )
                )

                # -------------------------------------------------
                # مستقیم TL object می‌سازیم.
                #
                # Button.inline() در SPlusthon 1.1.4
                # به KeyboardButtonCopy دسترسی دارد،
                # در حالی که این type در همان نسخه وجود ندارد.
                #
                # بنابراین helper خراب SPlusthon را دور می‌زنیم.
                # -------------------------------------------------

                rendered_buttons.append(
                    types.KeyboardButtonCallback(
                        button.label,
                        token,
                    )
                )

            if rendered_buttons:

                rendered_rows.append(
                    types.KeyboardButtonRow(
                        rendered_buttons
                    )
                )

        if not rendered_rows:
            return None

        # مهم:
        # یک ReplyInlineMarkup آماده برمی‌گردانیم تا
        # SPlusthon دیگر build_reply_markup() را روی تک‌تک
        # buttonها اجرا نکند و وارد Button._is_inline() نشود.
        return types.ReplyInlineMarkup(
            rendered_rows
        )
    # =========================================================
    # CALLBACK REGISTRY
    # =========================================================

    async def _answer_callback(
        self,
        event,
        *,
        message: str | None = None,
        alert: bool = False,
    ) -> None:

        if getattr(
            event,
            "_spbot_callback_answered",
            False,
        ):
            return

        event._spbot_callback_answered = True

        try:

            await self.client(
                SetBotCallbackAnswerRequest(
                    query_id=event.id,
                    message=message,
                    alert=alert,
                    cache_time=0,
                )
            )

        except Exception:

            print(
                "\n⚠️ پاسخ CallbackQuery "
                "ناموفق بود:"
            )

            traceback.print_exc()

    def _cleanup_callbacks(self) -> None:

        now = time.time()

        expired = [
            token
            for token, action
            in self._callbacks.items()
            if (
                now
                - action.created_at
                > self.CALLBACK_TTL
            )
        ]

        for token in expired:
            self._callbacks.pop(
                token,
                None,
            )

        # سقف حافظه
        if len(
            self._callbacks
        ) <= self.MAX_CALLBACKS:
            return

        ordered = sorted(
            self._callbacks.items(),
            key=lambda item:
                item[1].created_at,
        )

        remove_count = (
            len(self._callbacks)
            - self.MAX_CALLBACKS
        )

        for token, _ in ordered[
            :remove_count
        ]:
            self._callbacks.pop(
                token,
                None,
            )

    def _create_callback(
        self,
        command,
        args_text: str,
    ) -> bytes:

        self._cleanup_callbacks()

        token = (
            secrets.token_urlsafe(9)
        )

        while token in self._callbacks:

            token = (
                secrets.token_urlsafe(9)
            )

        self._callbacks[token] = (
            _CallbackAction(
                command_name=command.name,
                args_text=args_text,
                created_at=time.time(),
            )
        )

        return (
            self.CALLBACK_PREFIX
            + token.encode("ascii")
        )

    # =========================================================
    # CALLBACK DISPATCHER
    # =========================================================

    def _register_callback_dispatcher(
        self,
    ) -> None:

        @self.client.on(
            events.CallbackQuery
        )
        async def ui_callback_dispatcher(
            event: events.CallbackQuery.Event,
        ) -> None:

            data = event.data

            if isinstance(
                data,
                str,
            ):
                data = data.encode(
                    "utf-8"
                )

            if not data.startswith(
                self.CALLBACK_PREFIX
            ):
                return

            token = (
                data[
                    len(self.CALLBACK_PREFIX):
                ]
                .decode(
                    "ascii",
                    errors="ignore",
                )
            )

            self._cleanup_callbacks()

            action = (
                self._callbacks.get(
                    token
                )
            )

            if action is None:

                await self._answer_callback(
                    event,
                    message="این دکمه منقضی شده است.",
                    alert=True,
                )

                return

            command = (
                self.command_manager
                .get_command(
                    action.command_name
                )
            )

            if command is None:

                await self._answer_callback(
                    event,
                    message="این دستور دیگر فعال نیست.",
                    alert=True,
                )

                return

            # -------------------------------------------------
            # EVENT ADAPTER
            # -------------------------------------------------

            event.command_prefix = (
                getattr(
                    self.transport,
                    "command_prefix",
                    "/",
                )
            )

            event.args_text = (
                action.args_text
            )

            event.args = (
                action.args_text.split()
                if action.args_text
                else []
            )

            event.raw_text = (
                self.command_manager
                .format_command(
                    command,
                    action.args_text,
                    event=event,
                )
            )

            event.command = command

            # بعضی Pluginها ممکن است Message را بخواهند.
            # CallbackQuery خودش get_message() دارد.
            try:

                message = (
                    await event.get_message()
                )

                if message is not None:
                    event.message = message

            except Exception:
                pass

            # -------------------------------------------------
            # EXECUTE
            # -------------------------------------------------

            try:

                handled = (
                    await self.command_manager
                    .execute_command(
                        command,
                        event,
                        action.args_text,
                    )
                )

                if not handled:

                    await self._answer_callback(
                        event,
                        message="اجازه‌ی اجرای این دستور را نداری.",
                        alert=True,
                    )

                    return

            except Exception:

                print(
                    "\n❌ خطای بحرانی در اجرای "
                    "Command از طریق UI:"
                )

                traceback.print_exc()

                try:

                    await self._answer_callback(
                        event,
                        message="❌ هنگام اجرای این دستور خطایی رخ داد.",
                        alert=True,
                    )

                except Exception:
                    pass

                return

            finally:

                await self._answer_callback(
                    event
                )

            raise StopPropagation