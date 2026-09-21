"""
دکوریتورهای کمکی برای نوشتن پلاگین‌ها.

این‌ها فقط «برچسب» روی متد می‌گذارند.
ثبت واقعی توسط BasePlugin انجام می‌شود.
"""

from typing import (
    Any,
    Callable,
    TypeVar,
    Iterable,
    Optional
)


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
    """
    متد را به‌عنوان Handler یک Command علامت‌گذاری می‌کند.
    """

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
    """
    متد را به‌عنوان Event Handler علامت‌گذاری می‌کند.
    """

    def decorator(
        func: F,
    ) -> F:

        func._event_type = event_type

        return func

    return decorator


def on_bus_event(
    event_name: str,
) -> Callable[[F], F]:
    """
    متد را به‌عنوان Listener یک EventBus event
    علامت‌گذاری می‌کند.
    """

    def decorator(
        func: F,
    ) -> F:

        func._bus_event_name = event_name

        return func

    return decorator

def on_command_invocation(*, priority: int = 0, commands: Optional[Iterable[str]] = None):
    def decorator(func):
        func._command_invocation_hook = True
        func._command_invocation_priority = priority
        func._command_invocation_commands = frozenset(commands) if commands else None
        return func
    return decorator