"""
دکوریتورهای کمکی برای نوشتن پلاگین‌ها.

این‌ها فقط یه «برچسب» روی متد پلاگین می‌ذارن؛ ثبت واقعی‌شون (توی
command_manager یا روی client) توسط BasePlugin._register_decorated موقع
فعال‌سازی پلاگین انجام می‌شه. یعنی پلاگین‌نویس فقط کافیه دکوریتور رو
بذاره روی یه متد از کلاس پلاگین، نیازی به فایل جدا یا صدا زدن دستی
add_command نیست.
"""


def command(name: str, permission: str = "everyone", chat_type: str = "all"):
    """
    متد رو به‌عنوان هندلر یک کامند علامت‌گذاری می‌کنه.

    مثال:
        class MyPlugin(BasePlugin):
            @command(name="پینگ")
            async def ping(self, event):
                await event.reply("pong")

    داخل event.args_text متن بعد از نام کامند (خام) و داخل event.args
    همون متن split‌شده به لیست در دسترسه.
    """

    def decorator(func):
        func._command_info = {
            "name": name,
            "permission": permission,
            "chat_type": chat_type,
        }
        return func

    return decorator


def on_event(event_type):
    """
    متد رو به‌عنوان هندلر یک event (مثل events.NewMessage) علامت‌گذاری می‌کنه.

    مثال:
        class MyPlugin(BasePlugin):
            @on_event(events.NewMessage(incoming=True))
            async def on_message(self, event):
                ...
    """

    def decorator(func):
        func._event_type = event_type
        return func

    return decorator
