from __future__ import annotations

import inspect
import itertools
import traceback

from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterable,
    Optional,
)

from splusthon import (
    SoroushClient,
    events,
)
from splusthon.events import StopPropagation

from core.command_invocation import (
    CommandInvocation,
)
from core.permissions import (
    is_chat_admin,
    is_owner,
)


EventHandler = Callable[
    [Any],
    Awaitable[Any],
]

InvocationHook = Callable[
    [CommandInvocation],
    Awaitable[Any] | Any,
]


@dataclass
class Command:
    name: str
    handler: EventHandler
    permission: str = "everyone"
    chat_type: str = "all"
    description: str = ""
    plugin: Optional[object] = None


@dataclass
class _InvocationHookRegistration:
    priority: int
    order: int
    callback: InvocationHook


class CommandManager:
    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

        self.prefix = "!"

        self._client: SoroushClient | None = None

        self._invocation_hooks: list[
            _InvocationHookRegistration
        ] = []

        self._hook_order = itertools.count()

    # =========================================================
    # Command Registration
    # =========================================================

    def add_command(
        self,
        name: str,
        handler: EventHandler,
        permission: str = "everyone",
        chat_type: str = "all",
        description: str = "",
        plugin: Optional[object] = None,
    ) -> None:

        if name in self.commands:
            owner = self.commands[
                name
            ].plugin

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

        self.commands[name] = Command(
            name=name,
            handler=handler,
            permission=permission,
            chat_type=chat_type,
            description=description,
            plugin=plugin,
        )

    def get_command(
        self,
        name: str,
    ) -> Optional[Command]:

        return self.commands.get(name)

    def remove_command(
        self,
        name: str,
    ) -> None:

        self.commands.pop(
            name,
            None,
        )

    def remove_plugin_commands(
        self,
        plugin: object,
    ) -> None:

        commands_to_remove = [
            name
            for name, command
            in self.commands.items()
            if command.plugin is plugin
        ]

        for name in commands_to_remove:
            self.remove_command(name)

    def get_all_commands(
        self,
    ) -> Iterable[Command]:

        return self.commands.values()

    # =========================================================
    # Invocation Hooks
    # =========================================================

    def add_invocation_hook(
        self,
        hook: InvocationHook,
        *,
        priority: int = 0,
    ) -> None:
        """
        Hook را برای Invocation ثبت می‌کند.

        priority کمتر = زودتر اجرا شدن.

        اگر همان Hook قبلاً ثبت شده باشد،
        دوباره ثبت نمی‌شود.
        """

        for registration in (
            self._invocation_hooks
        ):
            if (
                registration.callback
                == hook
            ):
                return

        registration = (
            _InvocationHookRegistration(
                priority=priority,
                order=next(
                    self._hook_order
                ),
                callback=hook,
            )
        )

        self._invocation_hooks.append(
            registration
        )

        self._invocation_hooks.sort(
            key=lambda item: (
                item.priority,
                item.order,
            )
        )

    def remove_invocation_hook(
        self,
        hook: InvocationHook,
    ) -> None:

        self._invocation_hooks = [
            registration
            for registration
            in self._invocation_hooks
            if registration.callback
            != hook
        ]

    async def _run_invocation_hooks(
        self,
        invocation: CommandInvocation,
    ) -> None:

        if not self._invocation_hooks:
            return

        for registration in list(
            self._invocation_hooks
        ):
            if invocation.stop_hooks:
                break

            try:
                result = registration.callback(
                    invocation
                )

                if inspect.isawaitable(
                    result
                ):
                    await result

            except Exception:
                print(
                    "\n❌ خطا در Command Invocation Hook"
                )

                traceback.print_exc()

                # بسیار مهم:
                # Hookی که در کنترل Command خطا بدهد،
                # نباید باعث اجرای ناخواسته‌ی Command شود.
                #
                # بنابراین فقط همین Invocation
                # fail-closed می‌شود؛ کل Bot نه.
                invocation.block(
                    "Invocation Hook failed."
                )

    # =========================================================
    # Authorization
    # =========================================================

    async def _check_access(
        self,
        invocation: CommandInvocation,
    ) -> bool:

        command = (
            invocation.command
        )

        event = invocation.event

        # chat_type مربوط به Context فعلی است.
        if (
            command.chat_type
            == "group"
            and not event.is_group
        ):
            return False

        if (
            command.chat_type
            == "private"
            and not event.is_private
        ):
            return False

        # هویت Authorization همیشه از Event اصلی می‌آید.
        #
        # این باعث می‌شود یک Hook نتواند فقط با
        # replace_event() هویت کاربر را عوض کند
        # و Permission را دور بزند.
        original_event = (
            invocation.original_event
        )

        sender_id = (
            original_event.sender_id
        )

        if command.permission == "admin":

            chat = await event.get_chat()

            if self._client is None:
                raise RuntimeError(
                    "CommandManager client "
                    "has not been initialized."
                )

            return await is_chat_admin(
                self._client,
                chat,
                sender_id,
            )

        if command.permission == "owner":

            return is_owner(
                sender_id
            )

        return True

    # =========================================================
    # Generic Command Invocation
    # =========================================================

    async def invoke(
        self,
        command_name: str,
        event: Any,
        *,
        args_text: str = "",
        source: str = "external",
        metadata: Optional[
            dict[str, Any]
        ] = None,
        pre_authorized: bool = False,
    ) -> CommandInvocation | None:
        """
        یک Command را از هر منبعی اجرا می‌کند.

        این متد هسته‌ی عمومی Command Execution است.

        مهم:
        این متد هیچ چیزی درباره‌ی Group Manager یا
        Remote Command نمی‌داند.
        """

        command = self.get_command(
            command_name
        )

        if command is None:
            return None

        invocation = CommandInvocation(
            command=command,
            original_event=event,
            args_text=(
                args_text or ""
            ).strip(),
            args=(
                args_text.split()
                if args_text
                else []
            ),
            source=source,
            metadata=(
                dict(metadata)
                if metadata
                else {}
            ),
        )

        # Context مربوط به آرگومان‌های Command.
        invocation.event.args_text = (
            invocation.args_text
        )

        invocation.event.args = list(
            invocation.args
        )

        if pre_authorized:
            invocation.grant_access()

        await self._run_invocation_hooks(
            invocation
        )

        if invocation.blocked:
            return invocation

        if invocation.handled:
            return invocation

        # Authorization طبیعی Command
        if (
            invocation.access_granted
            is None
        ):
            allowed = (
                await self._check_access(
                    invocation
                )
            )

            if not allowed:
                invocation.deny_access(
                    "Authorization denied."
                )

                return invocation

        elif not invocation.access_granted:
            invocation.deny_access(
                "Authorization denied."
            )

            return invocation

        handler = (
            invocation.handler
        )

        if handler is None:
            invocation.block(
                "Command has no handler."
            )

            return invocation

        invocation.executed = True
        invocation.consumed = True

        result = handler(
            invocation.event
        )

        if inspect.isawaitable(
            result
        ):
            await result

        return invocation

    # =========================================================
    # Command Matching
    # =========================================================

    def _match_command(
        self,
        body: str,
    ) -> tuple[
        Optional[str],
        str,
    ]:

        best_name: Optional[str] = None

        for name in self.commands:

            if (
                body == name
                or body.startswith(
                    name + " "
                )
            ):

                if (
                    best_name is None
                    or len(name)
                    > len(best_name)
                ):
                    best_name = name

        if best_name is None:
            return None, ""

        args_text = body[
            len(best_name):
        ].strip()

        return (
            best_name,
            args_text,
        )

    # =========================================================
    # Dispatcher
    # =========================================================

    def register_dispatcher(
        self,
        client: SoroushClient,
    ) -> None:

        self._client = client

        @client.on(
            events.NewMessage(
                incoming=True
            )
        )
        async def dispatcher(
            event: events.NewMessage.Event,
        ) -> None:

            command_name = "نامشخص"

            try:
                text = event.raw_text

                if (
                    not text
                    or not text.startswith(
                        self.prefix
                    )
                ):
                    return

                body = text[
                    len(self.prefix):
                ]

                if not body:
                    return

                matched_name, args_text = (
                    self._match_command(
                        body
                    )
                )

                if matched_name is None:
                    return

                command_name = matched_name

                invocation = await self.invoke(
                    command_name,
                    event,
                    args_text=args_text,
                    source="message",
                )

                if invocation is None:
                    return

                if invocation.consumed:
                    raise StopPropagation

                return

            except StopPropagation:
                raise

            except Exception:
                print(
                    "\n❌ خطای بحرانی در Command Dispatcher "
                    f"'{command_name}'"
                )

                traceback.print_exc()

                try:
                    await event.reply(
                        "❌ هنگام پردازش این دستور خطایی رخ داد."
                    )
                except Exception:
                    pass

                # چون این پیام Command معتبر بوده،
                # همچنان نباید به Handlerهای بعدی برسد.
                raise StopPropagation

        self._dispatcher = dispatcher