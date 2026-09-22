"""
دکوریتورهای کمکی برای نوشتن پلاگین‌ها.

این‌ها فقط یه «برچسب» روی متد پلاگین می‌ذارن؛ ثبت واقعی توسط
BasePlugin انجام می‌شه.
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
) -> Callable[[F], F]:

    def decorator(
        func: F,
    ) -> F:

        func._command_info = {
            "name": name,
            "permission": permission,
            "chat_type": chat_type,
            "description": description,
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