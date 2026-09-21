import inspect
import traceback

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional

from splusthon import SoroushClient, events
from splusthon.events import StopPropagation

from core.permissions import is_chat_admin, is_owner


EventHandler = Callable[[Any], Awaitable[Any]]
InvocationHook = Callable[
    ["CommandInvocation"],
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
class CommandInvocation:
    """
    نمایش عمومی یک تلاش برای اجرای Command.

    این کلاس عمداً مستقل از نوع منبع اجراست.
    بنابراین Invocation می‌تواند از پیام عادی، سیستم ریموت،
    Scheduler، پنل مدیریتی یا هر منبع دیگری ساخته شود.
    """

    command: Command
    event: Any

    args_text: str = ""
    args: list[str] = field(default_factory=list)

    source: str = "message"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    handler: EventHandler | None = None

    access_granted: bool | None = None

    blocked: bool = False
    handled: bool = False

    def __post_init__(self) -> None:
        if self.handler is None:
            self.handler = self.command.handler

    @property
    def command_name(self) -> str:
        return self.command.name

    def replace_handler(
        self,
        handler: EventHandler,
    ) -> None:
        """
        Handler اصلی را برای همین Invocation عوض می‌کند.
        """

        self.handler = handler

    def replace_event(
        self,
        event: Any,
    ) -> None:
        """
        Context/Event مورد استفاده توسط handler را عوض می‌کند.
        """

        self.event = event

    def set_args(
        self,
        args_text: str,
    ) -> None:
        """
        آرگومان‌های Invocation را تغییر می‌دهد.
        """

        self.args_text = args_text.strip()

        self.args = (
            self.args_text.split()
            if self.args_text
            else []
        )

        self.event.args_text = self.args_text
        self.event.args = list(self.args)

    def grant_access(self) -> None:
        """
        می‌گوید Authorization این Invocation قبلاً
        توسط یک لایهٔ قابل اعتماد انجام شده است.
        """

        self.access_granted = True

    def deny_access(self) -> None:
        """
        این Invocation نباید اجرا شود.
        """

        self.access_granted = False

    def block(self) -> None:
        """
        اجرای این Command را متوقف می‌کند.
        """

        self.blocked = True

    def mark_handled(self) -> None:
        """
        یعنی Hook خودش Command را مدیریت کرده و
        دیگر نباید Handler اصلی اجرا شود.
        """

        self.handled = True


class CommandManager:
    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

        self.prefix = "!"

        self._invocation_hooks: list[
            InvocationHook
        ] = []

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
            owner = self.commands[name].plugin

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
            for name, command in self.commands.items()
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
    ) -> None:
        """
        یک Hook عمومی برای Invocation ثبت می‌کند.
        """

        if hook in self._invocation_hooks:
            return

        self._invocation_hooks.append(
            hook
        )

    def remove_invocation_hook(
        self,
        hook: InvocationHook,
    ) -> None:

        if hook in self._invocation_hooks:
            self._invocation_hooks.remove(
                hook
            )

    async def _run_invocation_hooks(
        self,
        invocation: CommandInvocation,
    ) -> None:

        if not self._invocation_hooks:
            return

        for hook in list(
            self._invocation_hooks
        ):
            try:
                result = hook(
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

                # خطای یک Hook نباید اجرای بقیه
                # سیستم Command را مختل کند.

    # =========================================================
    # Authorization
    # =========================================================

    async def _check_access(
        self,
        command: Command,
        event: Any,
    ) -> bool:

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

        sender_id = event.sender_id

        if command.permission == "admin":

            chat = await event.get_chat()

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
    ) -> bool:

        command = self.get_command(
            command_name
        )

        if command is None:
            return False

        invocation = CommandInvocation(
            command=command,
            event=event,
            args_text=args_text,
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

        # Context فعلی Event را نیز sync می‌کنیم.
        event.args_text = (
            invocation.args_text
        )

        event.args = list(
            invocation.args
        )

        if pre_authorized:
            invocation.grant_access()

        await self._run_invocation_hooks(
            invocation
        )

        if invocation.blocked:
            return True

        if invocation.handled:
            return True

        # اگر Hook قبلاً Authorization را مشخص نکرده،
        # مسیر عادی Permission/Chat Type را اجرا می‌کنیم.
        if (
            invocation.access_granted
            is None
        ):

            allowed = (
                await self._check_access(
                    command,
                    invocation.event,
                )
            )

            if not allowed:
                return False

        elif not invocation.access_granted:
            return False

        handler = invocation.handler

        if handler is None:
            return False

        result = handler(
            invocation.event
        )

        if inspect.isawaitable(
            result
        ):
            await result

        return True

    # =========================================================
    # Dispatcher
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
            handled = False

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

                handled = await self.invoke(
                    command_name,
                    event,
                    args_text=args_text,
                    source="message",
                )

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
                        "❌ هنگام پردازش این پیام خطایی رخ داد."
                    )
                except Exception:
                    pass

            finally:
                if handled:
                    raise StopPropagation

        self._dispatcher = dispatcher