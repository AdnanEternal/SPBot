import inspect

from config import config
from core.command_manager import CommandManager
from core.database_manager import DatabaseManager


class BasePlugin:
    """
    کلاس پایه برای همه‌ی پلاگین‌ها.

    دو راه برای ثبت کامند / هندلر رویداد وجود داره:

    ۱) دکوریتور روی متدهای کلاس (روش پیشنهادی و ساده‌تر):
           from core.decorators import command, on_event

           class MyPlugin(BasePlugin):
               @command(name="پینگ", permission="admin", chat_type="group")
               async def ping(self, event):
                   await event.reply("pong")

               @on_event(events.NewMessage(incoming=True))
               async def on_message(self, event):
                   ...

       این‌ها خودکار موقع enable شدن پلاگین ثبت و موقع disable شدن پاک
       می‌شن. نیازی به فایل commands.py جدا یا صدا زدن دستی
       command_manager.add_command نیست.

    ۲) دستی داخل on_enable با self.listen(...) - برای مواقعی که نیاز به
       هندلرهای پویا/شرطی داری که از قبل به شکل متد کلاس قابل تعریف نیستن.
    """

    name = None
    version = "1.0.0"

    def __init__(
        self,
        client,
        command_manager: CommandManager,
        db: DatabaseManager,
    ):
        self.client = client
        self.command_manager = command_manager
        self.db = db
        self.enabled = False
        self.config = config
        self._event_handlers = []

    def listen(self, event_type):
        """
        دکوریتور برای ثبت دستیِ هندلر رویداد (مثلاً داخل on_enable).
        """

        def decorator(func):
            self.client.add_event_handler(func, event_type)
            self._event_handlers.append((func, event_type))
            return func

        return decorator

    def _register_decorated(self):
        """
        متدهایی که با @command یا @on_event علامت خوردن رو پیدا می‌کنه و
        خودش ثبتشون می‌کنه.
        """
        for _, member in inspect.getmembers(self, predicate=inspect.ismethod):
            command_info = getattr(member, "_command_info", None)
            if command_info:
                self.command_manager.add_command(
                    name=command_info["name"],
                    handler=member,
                    permission=command_info["permission"],
                    chat_type=command_info["chat_type"],
                    plugin=self,
                )

            event_type = getattr(member, "_event_type", None)
            if event_type is not None:
                self.client.add_event_handler(member, event_type)
                self._event_handlers.append((member, event_type))

    async def enable(self):
        """
        توسط PluginManager صدا زده می‌شه. خودت لازم نیست مستقیم صداش بزنی.
        """
        self._register_decorated()
        result = self.on_enable()
        if inspect.isawaitable(result):
            await result
        self.enabled = True

    async def disable(self):
        """
        توسط PluginManager صدا زده می‌شه. خودت لازم نیست مستقیم صداش بزنی.
        """
        result = self.on_disable()
        if inspect.isawaitable(result):
            await result
        await self.cleanup()
        self.enabled = False

    async def cleanup(self):
        """
        همه‌ی هندلرهای رویداد (چه دکوریتوری چه دستی) و همه‌ی کامندهای
        ثبت‌شده‌ی این پلاگین رو پاک می‌کنه.
        """
        for func, event_type in self._event_handlers:
            self.client.remove_event_handler(func, event_type)
        self._event_handlers.clear()
        self.command_manager.remove_plugin_commands(self)

    async def on_load(self):
        """
        فقط یک‌بار موقع discover_plugins صدا زده می‌شه.
        جای مناسب برای CREATE TABLE IF NOT EXISTS.
        """
        pass

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    def __repr__(self):
        return f"<Plugin {self.name} v{self.version}>"
