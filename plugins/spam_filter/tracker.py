"""
وضعیت کوتاه‌مدت و درجا (in-memory، نه دیتابیس) برای تشخیص فلاد و
پیام تکراری. عمداً تو دیتابیس ذخیره نمی‌شه چون عمرش کوتاهه و با
ری‌استارت ربات از نو شروع شدنش مشکلی نداره.
"""

import time
from collections import defaultdict, deque
from typing import Optional


class SpamTracker:
    CLEANUP_EVERY = 500   # هر چند پیام یه بار پاک‌سازی انجام بشه
    STALE_SECONDS = 200   # کاربری که ۱۰ دقیقه پیام نداده از حافظه پاک می‌شه

    def __init__(self) -> None:
        self._messages: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=100))
        self._last_text: dict[tuple[int, int], tuple[str, int]] = {}
        self._register_calls = 0

    def register(self, group_id: int, user_id: int, message_id: int, text: str) -> int:
        """
        پیام رو ثبت می‌کنه و تعداد تکرار پشت‌سرهمِ عین همین متن رو
        برمی‌گردونه (پیام غیرمتنی/خالی هیچ‌وقت «تکراری» حساب نمی‌شه).
        """
        self._register_calls += 1
        if self._register_calls % self.CLEANUP_EVERY == 0:
            self._cleanup()

        key = (group_id, user_id)
        self._messages[key].append((time.monotonic(), message_id))

        last_text, repeat_count = self._last_text.get(key, ("", 0))
        repeat_count = repeat_count + 1 if text and text == last_text else 1
        self._last_text[key] = (text, repeat_count)

        return repeat_count

    def clear_user(self, group_id: int, user_id: int) -> None:
        key = (group_id, user_id)
        self._messages.pop(key, None)
        self._last_text.pop(key, None)

    def _cleanup(self) -> None:
        cutoff = time.monotonic() - self.STALE_SECONDS
        stale = [
            key
            for key, messages in self._messages.items()
            if not messages or messages[-1][0] < cutoff
        ]
        for key in stale:
            self._messages.pop(key, None)
            self._last_text.pop(key, None)

    def count_in_window(self, group_id: int, user_id: int, seconds: int) -> int:
        cutoff = time.monotonic() - seconds
        messages = self._messages.get((group_id, user_id), ())
        return sum(1 for ts, _ in messages if ts >= cutoff)

    def ids_in_window(self, group_id: int, user_id: int, seconds: int) -> list[int]:
        cutoff = time.monotonic() - seconds
        messages = self._messages.get((group_id, user_id), ())
        return [mid for ts, mid in messages if ts >= cutoff]


class AdminCache:
    """
    is_chat_admin یه API call نسبتاً گرون می‌زنه؛ نتیجه رو چند دقیقه
    cache می‌کنیم که رو گروه‌های پرترافیک هر پیام یه API call نزنیم.
    """

    TTL_SECONDS = 300
    MAX_ENTRIES = 5000

    def __init__(self) -> None:
        self._cache: dict[tuple[int, int], tuple[bool, float]] = {}

    def get(self, group_id: int, user_id: int) -> Optional[bool]:
        entry = self._cache.get((group_id, user_id))
        if entry is None:
            return None

        is_admin, cached_at = entry
        if time.monotonic() - cached_at > self.TTL_SECONDS:
            return None
        return is_admin

    def set(
    self,
    group_id: int,
    user_id: int,
    is_admin: bool,
) -> None:
        key = (group_id, user_id)
        now = time.monotonic()

        if key not in self._cache:
            expired_keys = [
                cache_key
                for cache_key, (_, cached_at) in self._cache.items()
                if now - cached_at > self.TTL_SECONDS
            ]

            for cache_key in expired_keys:
                self._cache.pop(
                    cache_key,
                    None,
                )

            if len(self._cache) >= self.MAX_ENTRIES:
                oldest_key = min(
                    self._cache,
                    key=lambda cache_key:
                    self._cache[cache_key][1],
                )

                self._cache.pop(
                    oldest_key,
                    None,
                )

        self._cache[key] = (
            is_admin,
            now,
        )