"""
وضعیت کوتاه‌مدت و درجا (in-memory، نه دیتابیس) که برای تشخیص فلاد و
پیام تکراری لازمه. عمداً تو دیتابیس ذخیره نمی‌شه چون:
  - عمرش خیلی کوتاهه (چند ثانیه/دقیقه)
  - با ری‌استارت ربات از نو شروع بشه هیچ مشکلی نداره
برای همین جدا از store.py (که برای دیتای ماندگار مثل تنظیماته) نگه
داری می‌شه.
"""

import time
from collections import defaultdict, deque
from typing import Optional


class SpamTracker:
    def __init__(self) -> None:
        self._messages: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=100))
        self._last_text: dict[tuple[int, int], tuple[str, int]] = {}

    def register(self, group_id: int, user_id: int, message_id: int, text: str) -> int:
        """
        پیام رو ثبت می‌کنه و تعداد تکرار پشت‌سرهمِ عین همین متن رو
        برمی‌گردونه (پیام غیرمتنی/خالی هیچ‌وقت «تکراری» حساب نمی‌شه).
        """
        key = (group_id, user_id)
        self._messages[key].append((time.time(), message_id))

        last_text, repeat_count = self._last_text.get(key, ("", 0))
        repeat_count = repeat_count + 1 if text and text == last_text else 1
        self._last_text[key] = (text, repeat_count)

        return repeat_count

    def count_in_window(self, group_id: int, user_id: int, seconds: int) -> int:
        cutoff = time.time() - seconds
        return sum(1 for ts, _ in self._messages[(group_id, user_id)] if ts >= cutoff)

    def ids_in_window(self, group_id: int, user_id: int, seconds: int) -> list[int]:
        cutoff = time.time() - seconds
        return [mid for ts, mid in self._messages[(group_id, user_id)] if ts >= cutoff]


class AdminCache:
    """
    is_chat_admin یه API call می‌زنه (نسبتاً گرون)؛ چون تو این پلاگین
    باید رو *هر* پیام گروه چک بشه که فرستنده ادمین هست یا نه (تا معاف
    بشه)، نتیجه رو چند دقیقه cache می‌کنیم که رو گروه‌های پرترافیک هر
    پیام یه API call جدید نزنیم.
    """

    TTL_SECONDS = 300

    def __init__(self) -> None:
        self._cache: dict[tuple[int, int], tuple[bool, float]] = {}

    def get(self, group_id: int, user_id: int) -> Optional[bool]:
        entry = self._cache.get((group_id, user_id))
        if entry is None:
            return None

        is_admin, cached_at = entry
        if time.time() - cached_at > self.TTL_SECONDS:
            return None
        return is_admin

    def set(self, group_id: int, user_id: int, is_admin: bool) -> None:
        self._cache[(group_id, user_id)] = (is_admin, time.time())
