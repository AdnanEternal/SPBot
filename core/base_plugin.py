import inspect
import traceback

from typing import (
    Any,
    Callable,
    Optional,
)

from splusthon import (
    SoroushClient,
)
from splusthon.events import (
    StopPropagation,
)

from config import config
from core.command_manager import (
    CommandManager,
)
from core.database_manager import (
    DatabaseManager,
)
from core.event_bus import (
    EventBus,
)


class BasePlugin:
    name: Optional[str] = None
    version: str = "1.0.0"

    def __init__(
        self,
        client: SoroushClient,
        command_manager: CommandManager,
        db: DatabaseManager,
        event_bus: EventBus,
    ) -> None:

        self.client = client
        self.command_manager = (
            command_manager
        )
        self.db = db
        self.event_bus = event_bus

        self.enabled = False
        self.config = config

        self._event_handlers: list[
            tuple[Callable, Any]
        ] = []

        self._bus_listeners: list[
            tuple[str, Callable]
        ] = []

        self._command_invocation_hooks: list[
            Callable
        ] = []

    # =========================================================
    # Event Wrapper
    # =========================================================

    def _wrap_event_handler(
        self,
        handler: Callable,
    ) -> Callable:

        async def wrapped(
            event,
        ):

            try:
                result = handler(
                    event
                )

                if inspect.isawaitable(
                    result
                ):
                    await result

            except StopPropagation:
                raise

            except Exception:
                print(
                    f"\n❌ خطا در Event Handler پلاگین "
                    f"'{self.name}' "
                    f"({getattr(handler, '__name__', 'unknown')})"
                )

                traceback.print_exc()

        wrapped.__name__ = getattr(
            handler,
            "__name__",
            "event_handler",
        )

        return wrapped

    # =========================================================
    # Manual Event Listener
    # =========================================================

    def listen(
        self,
        event_type: Any,
    ) -> Callable[[Callable], Callable]:

        def decorator(
            func: Callable,
        ) -> Callable:

            wrapped = (
                self._wrap_event_handler(
                    func
                )
            )

            self.client.add_event_handler(
                wrapped,
                event_type,
            )

            self._event_handlers.append(
                (
                    wrapped,
                    event_type,
                )
            )

            return func

        return decorator

    # =========================================================
    # Decorator Registration
    # =========================================================

    def _register_decorated(
        self,
    ) -> None:

        for _, member in inspect.getmembers(
            self,
            predicate=inspect.ismethod,
        ):

            # -------------------------------------------------
            # Command
            # -------------------------------------------------

            command_info = getattr(
                member,
                "_command_info",
                None,
            )

            if command_info:

                self.command_manager.add_command(
                    name=command_info["name"],
                    handler=member,
                    permission=command_info[
                        "permission"
                    ],
                    chat_type=command_info[
                        "chat_type"
                    ],
                    description=command_info.get(
                        "description",
                        "",
                    ),
                    plugin=self,
                )

            # -------------------------------------------------
            # SPlusthon Event
            # -------------------------------------------------

            event_type = getattr(
                member,
                "_event_type",
                None,
            )

            if event_type is not None:

                wrapped = (
                    self._wrap_event_handler(
                        member
                    )
                )

                self.client.add_event_handler(
                    wrapped,
                    event_type,
                )

                self._event_handlers.append(
                    (
                        wrapped,
                        event_type,
                    )
                )

            # -------------------------------------------------
            # Event Bus
            # -------------------------------------------------

            bus_event_name = getattr(
                member,
                "_bus_event_name",
                None,
            )

            if bus_event_name is not None:

                self.event_bus.on(
                    bus_event_name,
                    member,
                )

                self._bus_listeners.append(
                    (
                        bus_event_name,
                        member,
                    )
                )

            # -------------------------------------------------
            # Command Invocation Hook
            # -------------------------------------------------

            is_invocation_hook = getattr(
                member,
                "_command_invocation_hook",
                False,
            )

            if is_invocation_hook:

                priority = getattr(
                    member,
                    "_command_invocation_priority",
                    0,
                )

                self.command_manager.add_invocation_hook(
                    member,
                    priority=priority,
                    commands=getattr(member, "_command_invocation_commands", None)
                )

                self._command_invocation_hooks.append(
                    member
                )

    # =========================================================
    # Enable / Disable
    # =========================================================

    async def enable(
        self,
    ) -> None:

        if self.enabled:
            return

        try:

            self._register_decorated()

            result = self.on_enable()

            if inspect.isawaitable(
                result
            ):
                await result

            self.enabled = True

        except Exception:

            print(
                f"\n❌ خطا هنگام فعال‌سازی پلاگین "
                f"'{self.name}'"
            )

            traceback.print_exc()

            try:
                await self.cleanup()

            except Exception:

                print(
                    f"⚠️ خطا هنگام پاک‌سازی پلاگین "
                    f"'{self.name}'"
                )

                traceback.print_exc()

            self.enabled = False

            raise

    async def disable(
        self,
    ) -> None:

        try:

            result = self.on_disable()

            if inspect.isawaitable(
                result
            ):
                await result

        except Exception:

            print(
                f"\n❌ خطا در on_disable پلاگین "
                f"'{self.name}'"
            )

            traceback.print_exc()

        finally:

            try:
                await self.cleanup()

            except Exception:

                print(
                    f"\n❌ خطا در cleanup پلاگین "
                    f"'{self.name}'"
                )

                traceback.print_exc()

            self.enabled = False

    # =========================================================
    # Cleanup
    # =========================================================

    async def cleanup(
        self,
    ) -> None:

        # SPlusthon events
        for (
            func,
            event_type,
        ) in self._event_handlers:

            try:

                self.client.remove_event_handler(
                    func,
                    event_type,
                )

            except Exception:

                traceback.print_exc()

        self._event_handlers.clear()

        # Event Bus
        for (
            event_name,
            func,
        ) in self._bus_listeners:

            try:

                self.event_bus.off(
                    event_name,
                    func,
                )

            except Exception:

                traceback.print_exc()

        self._bus_listeners.clear()

        # Command Invocation Hooks
        for hook in (
            self._command_invocation_hooks
        ):

            try:

                self.command_manager.remove_invocation_hook(
                    hook
                )

            except Exception:

                traceback.print_exc()

        self._command_invocation_hooks.clear()

        # Commands
        self.command_manager.remove_plugin_commands(
            self
        )
        self.command_manager.scheduler.cancel_owner(self)

    # =========================================================
    # Lifecycle
    # =========================================================

    async def on_load(
        self,
    ) -> None:
        pass

    async def on_enable(
        self,
    ) -> None:
        pass

    async def on_disable(
        self,
    ) -> None:
        pass

    # =========================================================
    # Debug
    # =========================================================

    def __repr__(
        self,
    ) -> str:

        return (
            f"<Plugin {self.name} "
            f"v{self.version}>"
        )