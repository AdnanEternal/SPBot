# core/command_manager.py

import re
import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional

from splusthon import SoroushClient, events
from splusthon.events import StopPropagation

from core.permissions import is_chat_admin, is_owner


EventHandler = Callable[[Any], Awaitable[Any]]
_NATIVE_NAME_PATTERN = re.compile(
    r"^[a-z0-9_]{1,32}$"
)


@dataclass
class Command:
    name: str
    handler: EventHandler
    permission: str = "everyone"
    chat_type: str = "all"
    description: str = ""
    native_name: str = ""
    plugin: Optional[object] = None


class CommandManager:
    """
    نگهدارنده و dispatcher کامندها.

    این کلاس فقط مسئول:
        - ثبت Command
        - حذف Command
        - پیدا کردن Command
        - dispatch کردن ! و /
        - استخراج arguments

    این کلاس هیچ اطلاعی از Transport یا Native Command Menu ندارد.
    """

    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

        # Interface پیش‌فرض UserBot.
        # Transport هنگام ساخت PluginManager این مقادیر را تنظیم می‌کند.
        self.prefix = "!"
        self.command_name_field = "name"
        self.command_display_backticks = True

        self._client: SoroushClient | None = None


    # =========================================================
    # REGISTRY
    # =========================================================
    def add_command(
        self,
        name: str,
        handler: EventHandler,
        permission: str = "everyone",
        chat_type: str = "all",
        description: str = "",
        native_name: str | None = None,
        plugin: Optional[object] = None,
    ) -> None:

        name = str(name).strip()

        if not name:
            raise ValueError(
                "❌ نام command نمی‌تواند خالی باشد."
            )

        # ---------------------------------------------------------
        # EXISTING COMMAND
        # ---------------------------------------------------------

        existing = self.commands.pop(
            name,
            None,
        )

        if existing is not None:

            owner = existing.plugin

            owner_name = (
                owner.name
                if owner
                else "نامشخص"
            )

            print(
                f"⚠️ کامند '{name}' قبلاً توسط "
                f"پلاگین '{owner_name}' ثبت شده بود "
                f"و حالا بازنویسی می‌شه."
            )

        # ---------------------------------------------------------
        # NATIVE NAME
        # ---------------------------------------------------------

        resolved_native_name = (
            self._resolve_native_name(
                handler=handler,
                requested_name=native_name,
            )
        )

        # ---------------------------------------------------------
        # REGISTER
        # ---------------------------------------------------------

        self.commands[name] = Command(
            name=name,
            handler=handler,
            permission=permission,
            chat_type=chat_type,
            description=description,
            native_name=resolved_native_name,
            plugin=plugin,
        )

    def _resolve_native_name(
        self,
        *,
        handler: EventHandler,
        requested_name: str | None,
    ) -> str:

        # ---------------------------------------------------------
        # EXPLICIT NAME
        # ---------------------------------------------------------

        if requested_name is not None:

            candidate = str(
                requested_name
            ).strip().lower()

            if not candidate:

                print(
                    "⚠️ native_name خالی است؛ "
                    "از fallback استفاده می‌شود."
                )

            elif _NATIVE_NAME_PATTERN.fullmatch(
                candidate
            ):

                if not self._native_name_in_use(
                    candidate
                ):
                    return candidate

                print(
                    f"⚠️ native_name '{candidate}' "
                    "قبلاً استفاده شده؛ "
                    "از fallback استفاده می‌شود."
                )

            else:

                print(
                    f"⚠️ native_name '{candidate}' "
                    "برای Native Command معتبر نیست؛ "
                    "از fallback استفاده می‌شود."
                )

        # ---------------------------------------------------------
        # HANDLER NAME
        # ---------------------------------------------------------

        handler_name = str(
            getattr(
                handler,
                "__name__",
                "",
            )
            or ""
        ).strip().lower()

        if (
            handler_name
            and _NATIVE_NAME_PATTERN.fullmatch(
                handler_name
            )
            and not self._native_name_in_use(
                handler_name
            )
        ):
            return handler_name

        # ---------------------------------------------------------
        # FALLBACK
        # ---------------------------------------------------------

        return self._generate_fallback_native_name()


    def _native_name_in_use(
        self,
        native_name: str,
    ) -> bool:

        return any(
            command.native_name == native_name
            for command in self.commands.values()
        )


    def _generate_fallback_native_name(
        self,
    ) -> str:

        index = 1

        while True:

            candidate = (
                f"untitled_{index}"
            )

            if not self._native_name_in_use(
                candidate
            ):
                return candidate

            index += 1


    def get_command(
        self,
        name: str,
    ) -> Optional[Command]:
        return self.commands.get(name)

    def remove_command(
        self,
        name: str,
    ) -> None:
        self.commands.pop(name, None)

    def remove_plugin_commands(
        self,
        plugin: object,
    ) -> None:

        commands_to_remove = [
            name
            for name, command in self.commands.items()
            if command.plugin is plugin
        ]

        for name in commands_to_remove:
            self.remove_command(name)

    def get_all_commands(
        self,
    ) -> Iterable[Command]:
        """
        Snapshot امن از registry.

        Transport نباید روی dict زنده‌ی CommandManager کار کند.
        """
        return tuple(
            self.commands.values()
        )
    
    def resolve_command(
        self,
        command_or_name,
    ) -> Optional[Command]:

        # خود Command
        if isinstance(
            command_or_name,
            Command,
        ):
            return command_or_name

        # handler
        if callable(
            command_or_name
        ):

            candidate_func = getattr(
                command_or_name,
                "__func__",
                command_or_name,
            )

            candidate_self = getattr(
                command_or_name,
                "__self__",
                None,
            )

            for command in self.commands.values():

                handler = command.handler

                handler_func = getattr(
                    handler,
                    "__func__",
                    handler,
                )

                handler_self = getattr(
                    handler,
                    "__self__",
                    None,
                )

                if (
                    handler_func is candidate_func
                    and handler_self is candidate_self
                ):
                    return command

            return None

        # نام داخلی
        name = str(
            command_or_name
        ).strip()

        if not name:
            return None

        command = self.commands.get(
            name
        )

        if command is not None:
            return command

        # native name
        name_lower = name.lower()

        for command in self.commands.values():

            if (
                command.native_name
                and command.native_name
                == name_lower
            ):
                return command

        return None


    def get_display_name(
        self,
        command_or_name,
    ) -> str:

        command = self.resolve_command(
            command_or_name
        )

        if command is None:
            raise ValueError(
                f"کامند '{command_or_name}' "
                "در registry پیدا نشد."
            )

        command_name = getattr(
            command,
            self.command_name_field,
            None,
        )

        if not command_name:

            raise ValueError(
                f"کامند '{command.name}' "
                f"مقدار معتبر برای "
                f"'{self.command_name_field}' ندارد."
            )

        return str(
            command_name
        )


    def format_command(
        self,
        command_or_name,
        args_text: str = "",
        *,
        event=None,
    ) -> str:

        command_name = (
            self.get_display_name(
                command_or_name
            )
        )

        prefix = self.prefix

        if event is not None:

            event_prefix = getattr(
                event,
                "command_prefix",
                None,
            )

            if event_prefix:
                prefix = event_prefix

        result = (
            f"{prefix}"
            f"{command_name}"
        )

        args_text = str(
            args_text or ""
        ).strip()

        if args_text:
            result += (
                f" {args_text}"
            )

        if self.command_display_backticks:
            return f"`{result}`"

        return result


    def is_command_message(
        self,
        text: str,
    ) -> bool:

        text = (
            text or ""
        ).strip()

        if not text:
            return False

        return text.startswith(
            self.prefix
        )

        # =========================================================
    # COMMAND EXECUTION
    # =========================================================

    async def execute_command(
        self,
        command: Command,
        event,
        args_text: str = "",
    ) -> bool:

        if command is None:
            return False

        # -------------------------------------------------
        # CHAT TYPE
        # -------------------------------------------------

        if (
            command.chat_type == "group"
            and not event.is_group
        ):
            return False

        if (
            command.chat_type == "private"
            and not event.is_private
        ):
            return False

        # -------------------------------------------------
        # PERMISSION
        # -------------------------------------------------

        sender_id = event.sender_id

        if command.permission == "admin":

            chat = await event.get_chat()

            if not await is_chat_admin(
                self._client,
                chat,
                sender_id,
            ):
                return False

        elif command.permission == "owner":

            if not is_owner(sender_id):
                return False

        # -------------------------------------------------
        # EVENT CONTEXT
        # -------------------------------------------------

        event.command = command

        event.args_text = str(
            args_text or ""
        ).strip()

        event.args = (
            event.args_text.split()
            if event.args_text
            else []
        )

        # -------------------------------------------------
        # EXECUTE
        # -------------------------------------------------

        await command.handler(
            event
        )

        return True
    
    # =========================================================
    # DISPATCHER
    # =========================================================

    def register_dispatcher(
        self,
        client: SoroushClient,
    ) -> None:

        self._client = client

        @client.on(events.NewMessage(incoming=True))
        async def dispatcher(
            event: events.NewMessage.Event,
        ) -> None:

            command_name = "نامشخص"
            handled = False

            try:
                text = (
                    event.raw_text
                    or ""
                ).strip()

                if not text:
                    return

                # -------------------------------------------------
                # PREFIX
                #
                # !command
                # /command
                # /
                # -------------------------------------------------
                prefix = self.prefix

                if not text.startswith(
                    prefix
                ):
                    return

                body = (
                    text[len(prefix):]
                    .strip()
                )

                # فقط Standard/native interface:
                # "/" به‌تنهایی = راهنما
                #
                # این یک special entry point است.
                # "/راهنما" همچنان Command معمولی نیست.
                if (
                    prefix == "/"
                    and not body
                ):
                    command = self.commands.get(
                        "راهنما"
                    )

                    if command is None:
                        return

                    body = command.native_name

                event.command_prefix = prefix

                if not body:
                    return

                # -------------------------------------------------
                # /command@BotName
                # -------------------------------------------------

                if prefix == "/":

                    first_space = body.find(" ")

                    if first_space == -1:
                        command_part = body
                        args_part = ""

                    else:
                        command_part = (
                            body[:first_space]
                        )

                        args_part = (
                            body[first_space:]
                            .strip()
                        )

                    if "@" in command_part:
                        command_part = (
                            command_part.split(
                                "@",
                                1,
                            )[0]
                        )

                    body = (
                        command_part
                        + (
                            f" {args_part}"
                            if args_part
                            else ""
                        )
                    )

                # -------------------------------------------------
                # MATCH
                # -------------------------------------------------

                matched_name, args_text = (
                    self._match_command(
                        body
                    )
                )

                if matched_name is None:
                    return

                command_name = matched_name

                command = self.get_command(
                    command_name
                )

                if command is None:
                    return

                event.command = command

                # -------------------------------------------------
                # EXECUTE
                # -------------------------------------------------

                handled = True

                try:
                    await self.execute_command(
                        command,
                        event,
                        args_text,
                    )

                except Exception:

                    print(
                        f"\n❌ خطای بحرانی در اجرای دستور "
                        f"'{command_name}'"
                    )

                    traceback.print_exc()

                    try:
                        await event.reply(
                            "❌ هنگام اجرای این دستور خطایی رخ داد."
                        )

                    except Exception:
                        pass

            except StopPropagation:
                raise

            except Exception:

                print(
                    f"\n❌ خطای بحرانی در Command Dispatcher "
                    f"'{command_name}'"
                )

                traceback.print_exc()

                try:
                    await event.reply(
                        "❌ هنگام پردازش این پیام خطایی رخ داد."
                    )

                except Exception:
                    pass

            finally:

                if handled:
                    raise StopPropagation

        self._dispatcher = dispatcher

    # =========================================================
    # MATCHING
    # =========================================================

    def _match_command(
        self,
        body: str,
    ) -> tuple[Optional[str], str]:

        best_command: Optional[Command] = None
        best_match_length = -1

        for command in self.commands.values():

            command_name = getattr(
                command,
                self.command_name_field,
                None,
            )

            if not command_name:
                continue

            command_name = str(
                command_name
            )

            if (
                body == command_name
                or body.startswith(
                    command_name + " "
                )
            ):

                match_length = len(
                    command_name
                )

                if (
                    match_length
                    > best_match_length
                ):

                    best_command = command

                    best_match_length = (
                        match_length
                    )

        if best_command is None:
            return None, ""

        matched_name = getattr(
            best_command,
            self.command_name_field,
        )

        args_text = (
            body[
                len(matched_name):
            ]
            .strip()
        )

        return (
            best_command.name,
            args_text,
        )


    def resolve_command(
        self,
        command_or_name,
    ) -> Optional[Command]:

        # خود Command
        if isinstance(
            command_or_name,
            Command,
        ):
            return command_or_name

        # handler
        if callable(command_or_name):

            for command in self.commands.values():

                handler = command.handler

                if handler is command_or_name:
                    return command

                # bound method
                handler_func = getattr(
                    handler,
                    "__func__",
                    None,
                )

                candidate_func = getattr(
                    command_or_name,
                    "__func__",
                    None,
                )

                handler_self = getattr(
                    handler,
                    "__self__",
                    None,
                )

                candidate_self = getattr(
                    command_or_name,
                    "__self__",
                    None,
                )

                if (
                    handler_func is not None
                    and candidate_func is not None
                    and handler_func is candidate_func
                    and handler_self is candidate_self
                ):
                    return command

            return None

        # نام
        name = str(
            command_or_name
        ).strip()

        if not name:
            return None

        # ابتدا نام داخلی
        command = self.commands.get(
            name
        )

        if command is not None:
            return command

        # سپس native name
        name_lower = name.lower()

        for command in self.commands.values():

            if (
                command.native_name
                and command.native_name
                == name_lower
            ):
                return command

        return None


