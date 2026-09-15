import inspect
from typing import Any, Callable, Optional

from splusthon import SoroushClient

from config import config
from core.command_manager import CommandManager
from core.database_manager import DatabaseManager
from core.event_bus import EventBus


class BasePlugin:
    """
    کلاس پایه برای همه‌ی پلاگین‌ها.

    سه راه برای ثبت هندلر وجود داره، هر سه دکوریتوری و خودکار (ثبت موقع
    enable، پاک‌سازی موقع disable):

    ۱) @command - هندلر یه کامند متنی (!پینگ و ...)
    ۲) @on_event - هندلر یه رویداد splusthon (پیام جدید و ...)
    ۳) @on_bus_event - گوش‌دادن به رویدادی که یه پلاگین دیگه روی
       event_bus منتشر کرده، بدون اینکه به اون پلاگین import مستقیم
       داشته باشی.

    مثال:
        from core.decorators import command, on_event, on_bus_event

        class MyPlugin(BasePlugin):
            @command(name="پینگ", permission="admin", chat_type="group")
            async def ping(self, event):
                await event.reply("pong")

            @on_event(events.NewMessage(incoming=True))
            async def on_message(self, event):
                ...

            @on_bus_event("violation")
            async def on_violation(self, group_id, user_id, reason):
                ...

    یه راه چهارم هم برای موارد پویا/شرطی هست: self.listen(...) داخل
    on_enable، برای وقتایی که هندلر از قبل به شکل متد کلاس قابل تعریف
    نیست.
    """

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
        self.enabled: bool = False
        self.config = config
        self._event_handlers: list[tuple[Callable, Any]] = []
        self._bus_listeners: list[tuple[str, Callable]] = []

    def listen(self, event_type: Any) -> Callable[[Callable], Callable]:
        """
        دکوریتور برای ثبت دستیِ هندلر رویداد splusthon (مثلاً داخل on_enable).
        """

        def decorator(func: Callable) -> Callable:
            self.client.add_event_handler(func, event_type)
            self._event_handlers.append((func, event_type))
            return func

        return decorator

    def _register_decorated(self) -> None:
        """
        متدهایی که با @command، @on_event یا @on_bus_event علامت خوردن
        رو پیدا می‌کنه و خودش ثبتشون می‌کنه.
        """
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
                self._bus_listeners.append((bus_event_name, member))

    async def enable(self) -> None:
        """
        توسط PluginManager صدا زده می‌شه. خودت لازم نیست مستقیم صداش بزنی.
        """
        self._register_decorated()
        result = self.on_enable()
        if inspect.isawaitable(result):
            await result
        self.enabled = True

    async def disable(self) -> None:
        """
        توسط PluginManager صدا زده می‌شه. خودت لازم نیست مستقیم صداش بزنی.
        """
        result = self.on_disable()
        if inspect.isawaitable(result):
            await result
        await self.cleanup()
        self.enabled = False

    async def cleanup(self) -> None:
        """
        همه‌ی هندلرهای رویداد splusthon، همه‌ی گوش‌دهنده‌های event_bus، و
        همه‌ی کامندهای ثبت‌شده‌ی این پلاگین رو پاک می‌کنه.
        """
        for func, event_type in self._event_handlers:
            self.client.remove_event_handler(func, event_type)
        self._event_handlers.clear()

        for event_name, func in self._bus_listeners:
            self.event_bus.off(event_name, func)
        self._bus_listeners.clear()

        self.command_manager.remove_plugin_commands(self)

    async def on_load(self) -> None:
        """
        فقط یک‌بار موقع discover_plugins صدا زده می‌شه.
        جای مناسب برای CREATE TABLE IF NOT EXISTS.
        """
        pass

    async def on_enable(self) -> None:
        pass

    async def on_disable(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version}>"