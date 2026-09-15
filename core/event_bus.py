"""
یه pub/sub سبک برای ارتباط بین پلاگین‌ها بدون اینکه به هم import مستقیم
داشته باشن.

مثال: پلاگین content_filter وقتی یه کلمه‌ی فیلترشده پیدا می‌کنه، به‌جای
اینکه مستقیماً بره سراغ پلاگین violation_manager (که یعنی بهش وابسته
بشه و اگه violation_manager نصب نباشه crash کنه)، فقط می‌گه:

    await self.event_bus.emit("violation", group_id=.., user_id=.., reason=..)

هر پلاگینی (اگه باشه) که رو رویداد "violation" ثبت‌نام کرده باشه
(با دکوریتور @on_bus_event("violation")) صدا زده می‌شه. اگه هیچکس
subscribe نکرده باشه، emit بی‌اثره — یعنی هیچ پلاگینی به پلاگین دیگه‌ای
وابستگی سخت پیدا نمی‌کنه.
"""

from collections import defaultdict
from typing import Any, Awaitable, Callable

Listener = Callable[..., Awaitable[Any]]


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)

    def on(self, event_name: str, callback: Listener) -> None:
        self._listeners[event_name].append(callback)

    def off(self, event_name: str, callback: Listener) -> None:
        if callback in self._listeners[event_name]:
            self._listeners[event_name].remove(callback)

    async def emit(self, event_name: str, **kwargs: Any) -> None:
        for callback in list(self._listeners.get(event_name, [])):
            try:
                await callback(**kwargs)
            except Exception as e:
                print(f"❌ خطا تو هندلر رویداد '{event_name}': {e}")