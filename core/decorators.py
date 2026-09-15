"""
دکوریتورهای کمکی برای نوشتن پلاگین‌ها.

این‌ها فقط یه «برچسب» روی متد پلاگین می‌ذارن؛ ثبت واقعی‌شون (توی
command_manager، روی client، یا روی event_bus) توسط
BasePlugin._register_decorated موقع فعال‌سازی پلاگین انجام می‌شه. یعنی
پلاگین‌نویس فقط کافیه دکوریتور رو بذاره روی یه متد از کلاس پلاگین،
نیازی به فایل جدا یا صدا زدن دستی add_command نیست.
"""

from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def command(
    name: str,
    permission: str = "everyone",
    chat_type: str = "all",
    description: str = "",
) -> Callable[[F], F]:
    """
    متد رو به‌عنوان هندلر یک کامند علامت‌گذاری می‌کنه.

    مثال:
        class MyPlugin(BasePlugin):
            @command(name="پینگ", description="سلامت ربات رو چک می‌کنه.")
            async def ping(self, event):
                await event.reply("pong")

    داخل event.args_text متن بعد از نام کامند (خام) و داخل event.args
    همون متن split‌شده به لیست در دسترسه.

    description اختیاریه و برای خود کامند هیچ اثری نداره؛ فقط از طریق
    command_manager.get_all_commands() در دسترس بقیه‌ی پلاگین‌هاست (مثلاً
    پلاگین system که می‌خواد لیست همه‌ی کامندها رو با توضیح نشون بده).
    """

    def decorator(func: F) -> F:
        func._command_info = {
            "name": name,
            "permission": permission,
            "chat_type": chat_type,
            "description": description,
        }
        return func

    return decorator


def on_event(event_type: Any) -> Callable[[F], F]:
    """
    متد رو به‌عنوان هندلر یک event splusthon (مثل events.NewMessage)
    علامت‌گذاری می‌کنه. event_type نوعش رو Any گذاشتم چون به builder
    داخلی splusthon بستگی داره (events.NewMessage(...)، events.CallbackQuery(...) و ...).

    مثال:
        class MyPlugin(BasePlugin):
            @on_event(events.NewMessage(incoming=True))
            async def on_message(self, event):
                ...
    """

    def decorator(func: F) -> F:
        func._event_type = event_type
        return func

    return decorator


def on_bus_event(event_name: str) -> Callable[[F], F]:
    """
    متد رو به‌عنوان گوش‌دهنده‌ی یه رویداد داخلی (روی core/event_bus.py)
    علامت‌گذاری می‌کنه. این برخلاف on_event که مال رویدادهای splusthon
    (پیام جدید و ...) هست، برای ارتباط بین خودِ پلاگین‌هاست.

    مثال:
        class ViolationManagerPlugin(BasePlugin):
            @on_bus_event("violation")
            async def on_violation(self, group_id, user_id, reason):
                ...
    """

    def decorator(func: F) -> F:
        func._bus_event_name = event_name
        return func

    return decorator