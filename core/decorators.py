"""
دکوریتورهای کمکی برای نوشتن پلاگین‌ها.

این‌ها فقط metadata را روی متد پلاگین قرار می‌دهند؛
ثبت واقعی توسط BasePlugin و CommandManager انجام می‌شود.
"""

from typing import Any, Callable, TypeVar


F = TypeVar(
    "F",
    bound=Callable[..., Any],
)


def command(
    name: str,
    permission: str = "everyone",
    chat_type: str = "all",
    description: str = "",
    native_name: str | None = None,
) -> Callable[[F], F]:
    """
    ثبت metadata یک Command.

    native_name اختیاری است و فقط برای نمایش/ثبت در
    Native Command Menu استفاده می‌شود.

    اگر native_name تعیین نشود، CommandManager از نام
    تابع handler استفاده می‌کند.
    """

    def decorator(
        func: F,
    ) -> F:

        func._command_info = {
            "name": name,
            "permission": permission,
            "chat_type": chat_type,
            "description": description,
            "native_name": native_name,
        }

        return func

    return decorator


def on_event(
    event_type: Any,
) -> Callable[[F], F]:

    def decorator(
        func: F,
    ) -> F:

        func._event_type = event_type

        return func

    return decorator


def on_bus_event(
    event_name: str,
) -> Callable[[F], F]:

    def decorator(
        func: F,
    ) -> F:

        func._bus_event_name = event_name

        return func

    return decorator