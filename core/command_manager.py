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
from core.execution import (
    ExecutionEvent,
    Output,
)
from core.permissions import (
    is_chat_admin,
    is_owner,
)
from core.scheduler import Scheduler


EventHandler = Callable[
    [Any],
    Awaitable[Any],
]

InvocationHook = Callable[
    [CommandInvocation],
    Awaitable[Any] | Any,
]

# ترتیب سطح دسترسی‌ها (برای level=...)
_LEVELS = {
    "everyone": 0,
    "admin": 1,
    "owner": 2,
}


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
    # None = برای همه‌ی کامندها؛ وگرنه فقط برای این نام‌ها
    commands: frozenset[str] | None = None


class CommandManager:
    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

        self.prefix = "!"

        self._client: SoroushClient | None = None

        self._invocation_hooks: list[
            _InvocationHookRegistration
        ] = []

        self._hook_order = itertools.count()

        # زمان‌بندی اجرای کامند. روی CommandManager است تا همه‌ی
        # پلاگین‌ها بدون تغییر امضای BasePlugin بهش دسترسی داشته باشند.
        self.scheduler = Scheduler(self)

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
        commands: Iterable[str] | None = None,
    ) -> None:
        """
        Hook را برای Invocation ثبت می‌کند.

        priority کمتر = زودتر اجرا شدن.

        commands: اگر مشخص شود، Hook فقط برای همین کامندها
        (با نام دقیق) صدا زده می‌شود.

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
                commands=(
                    frozenset(commands)
                    if commands
                    else None
                ),
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

            if (
                registration.commands
                is not None
                and invocation.command_name
                not in registration.commands
            ):
                continue

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
    # Context / Authorization
    # =========================================================

    @staticmethod
    def _check_context(
        invocation: CommandInvocation,
    ) -> bool:
        """
        chat_type یک محدودیتِ «محیط اجراست»، نه Authorization؛
        پس حتی برای اجرای trusted/pre-authorized هم بررسی می‌شود.
        """

        command = invocation.command
        event = invocation.event

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

        return True

    async def _check_access(
        self,
        invocation: CommandInvocation,
    ) -> bool:

        command = (
            invocation.command
        )

        # سطح دسترسیِ اعطاشده (level=...) — فقط بالا می‌برد، پایین نمی‌آورد.
        if (
            invocation.granted_level
            is not None
            and _LEVELS.get(
                invocation.granted_level,
                -1,
            )
            >= _LEVELS.get(
                command.permission,
                len(_LEVELS),
            )
        ):
            return True

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

            chat = await invocation.event.get_chat()

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
        level: str | None = None,
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
            client=self._client,
            granted_level=level,
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

        # محیط اجرا (گروه/خصوصی) — مستقل از Authorization
        if not self._check_context(
            invocation
        ):
            invocation.deny_access(
                "Command is not available in this chat type."
            )

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
            result = await result

        invocation.result = result

        return invocation

    # =========================================================
    # Programmatic Execution (بدون پیامِ کاربر)
    # =========================================================

    async def run(
        self,
        command_name: str,
        args_text: str = "",
        *,
        chat_id: int | None = None,
        is_group: bool | None = None,
        as_user: int | None = None,
        level: str | None = None,
        trusted: bool = False,
        output: Output | None = None,
        event: Any = None,
        source: str = "programmatic",
        metadata: Optional[
            dict[str, Any]
        ] = None,
    ) -> CommandInvocation | None:
        """
        handler یک کامند را از داخل کد اجرا می‌کند؛ لازم نیست کسی چیزی تایپ کرده باشد.

        chat_id : handler فکر می‌کند در این چت اجرا می‌شود (event.chat_id، get_chat ...).
        is_group: نوع همان چت. اگر chat_id داده شود و is_group نه، گروه فرض می‌شود.
        as_user : هویت فرستنده (event.sender_id) — Authorization هم با همین سنجیده می‌شود.
        level   : "everyone" | "admin" | "owner"؛ کامندهای با این سطح یا پایین‌تر
                  بدون بررسی کاربر مجازند.
        trusted : اگر True، Authorization کلاً رد می‌شود (فقط برای کدِ خودت!).
        output  : مقصد event.reply؛ پیش‌فرض: event اصلی، وگرنه chat_id.
                  (Output.chat / owners / capture / silent / custom)
        event   : (اختیاری) event واقعی به‌عنوان base؛ مقدارهای override‌نشده از آن خوانده می‌شوند.

        بدون هیچ‌کدام از trusted/level/as_user (با مجوز)، کامندهای admin/owner رد می‌شوند.
        خروجی: CommandInvocation (.executed، .result، .block_reason ...) یا None اگر کامند نبود.
        خطای handler بالا می‌آید (Scheduler خودش لاگ می‌کند).
        """

        if self._client is None:
            raise RuntimeError(
                "CommandManager client "
                "has not been initialized."
            )

        if (
            level is not None
            and level not in _LEVELS
        ):
            raise ValueError(
                f"level نامعتبر: '{level}' "
                f"(یکی از {', '.join(_LEVELS)})"
            )

        if is_group is None and chat_id is not None:
            is_group = True

        args_text = (args_text or "").strip()

        execution_event = ExecutionEvent(
            self._client,
            base=event,
            chat_id=chat_id,
            sender_id=as_user,
            is_group=is_group,
            args_text=args_text,
            raw_text=(
                f"{self.prefix}{command_name} "
                f"{args_text}"
            ).strip(),
            output=output,
        )

        return await self.invoke(
            command_name,
            execution_event,
            args_text=args_text,
            source=source,
            metadata=metadata,
            pre_authorized=trusted,
            level=level,
        )

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