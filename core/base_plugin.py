# core/base_plugin.py

import inspect
import traceback
from typing import Any, Callable, Optional

from splusthon import SoroushClient

from config import config
from core.command_manager import CommandManager
from core.database_manager import DatabaseManager
from core.event_bus import EventBus


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
        self.command_manager = command_manager
        self.db = db
        self.event_bus = event_bus
        self.enabled = False
        self.config = config

        self._event_handlers: list[tuple[Callable, Any]] = []
        self._bus_listeners: list[tuple[str, Callable]] = []

    def listen(self, event_type: Any) -> Callable[[Callable], Callable]:
        def decorator(func: Callable) -> Callable:
            self.client.add_event_handler(func, event_type)
            self._event_handlers.append((func, event_type))
            return func

        return decorator

    def _register_decorated(self) -> None:
        for _, member in inspect.getmembers(self, predicate=inspect.ismethod):
            command_info = getattr(member, "_command_info", None)

            if command_info:
                self.command_manager.add_command(
                    name=command_info["name"],
                    handler=member,
                    permission=command_info["permission"],
                    chat_type=command_info["chat_type"],
                    description=command_info.get("description", ""),
                    plugin=self,
                )

            event_type = getattr(member, "_event_type", None)

            if event_type is not None:
                self.client.add_event_handler(member, event_type)
                self._event_handlers.append((member, event_type))

            bus_event_name = getattr(member, "_bus_event_name", None)

            if bus_event_name is not None:
                self.event_bus.on(bus_event_name, member)
                self._bus_listeners.append(
                    (bus_event_name, member)
                )

    async def enable(self) -> None:
        try:
            self._register_decorated()

            result = self.on_enable()

            if inspect.isawaitable(result):
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

    async def disable(self) -> None:
        try:
            result = self.on_disable()

            if inspect.isawaitable(result):
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

    async def cleanup(self) -> None:
        for func, event_type in self._event_handlers:
            try:
                self.client.remove_event_handler(
                    func,
                    event_type,
                )
            except Exception:
                traceback.print_exc()

        self._event_handlers.clear()

        for event_name, func in self._bus_listeners:
            try:
                self.event_bus.off(
                    event_name,
                    func,
                )
            except Exception:
                traceback.print_exc()

        self._bus_listeners.clear()

        self.command_manager.remove_plugin_commands(self)

    async def on_load(self) -> None:
        pass

    async def on_enable(self) -> None:
        pass

    async def on_disable(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version}>"