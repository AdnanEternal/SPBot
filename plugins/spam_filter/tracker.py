"""
State کوتاه‌مدت Spam Filter.

این فایل فقط رفتار اخیر کاربران را نگه می‌دارد:
- زمان پیام
- message id
- متن پیام
- تعداد تکرار پشت‌سرهم

داده‌های کوتاه‌مدت عمداً در RAM هستند.
"""

import time
from collections import defaultdict, deque
from typing import Optional


class SpamTracker:
    CLEANUP_EVERY = 500
    STALE_SECONDS = 600
    MAX_MESSAGES_PER_USER = 100

    def __init__(self) -> None:
        self._messages: dict[
            tuple[int, int],
            deque[
                tuple[float, int, str]
            ],
        ] = defaultdict(
            lambda: deque(
                maxlen=self.MAX_MESSAGES_PER_USER
            )
        )

        self._last_text: dict[
            tuple[int, int],
            tuple[str, int],
        ] = {}

        self._register_calls = 0

    def register(
        self,
        group_id: int,
        user_id: int,
        message_id: int,
        text: str,
    ) -> int:
        self._register_calls += 1

        if (
            self._register_calls
            % self.CLEANUP_EVERY
            == 0
        ):
            self._cleanup()

        key = (
            group_id,
            user_id,
        )

        self._messages[key].append(
            (
                time.monotonic(),
                message_id,
                text,
            )
        )

        last_text, repeat_count = (
            self._last_text.get(
                key,
                ("", 0),
            )
        )

        if (
            text
            and text == last_text
        ):
            repeat_count += 1
        else:
            repeat_count = 1

        self._last_text[key] = (
            text,
            repeat_count,
        )

        return repeat_count

    def clear_user(
        self,
        group_id: int,
        user_id: int,
    ) -> None:
        key = (
            group_id,
            user_id,
        )

        self._messages.pop(
            key,
            None,
        )

        self._last_text.pop(
            key,
            None,
        )

    def count_in_window(
        self,
        group_id: int,
        user_id: int,
        seconds: int,
    ) -> int:
        cutoff = (
            time.monotonic()
            - seconds
        )

        messages = self._messages.get(
            (group_id, user_id),
            (),
        )

        return sum(
            1
            for timestamp, _, _ in messages
            if timestamp >= cutoff
        )

    def ids_in_window(
        self,
        group_id: int,
        user_id: int,
        seconds: int,
    ) -> list[int]:
        cutoff = (
            time.monotonic()
            - seconds
        )

        messages = self._messages.get(
            (group_id, user_id),
            (),
        )

        return [
            message_id
            for timestamp, message_id, _ in messages
            if timestamp >= cutoff
        ]

    def recent_texts(
        self,
        group_id: int,
        user_id: int,
        limit: int = 10,
        exclude_message_id: int | None = None,
    ) -> list[str]:
        messages = self._messages.get(
            (group_id, user_id),
            (),
        )

        result: list[str] = []

        for _, message_id, text in reversed(messages):
            if (
                exclude_message_id is not None
                and message_id == exclude_message_id
            ):
                continue

            if not text:
                continue

            result.append(text)

            if len(result) >= limit:
                break

        return result

    def _cleanup(self) -> None:
        cutoff = (
            time.monotonic()
            - self.STALE_SECONDS
        )

        stale_keys = [
            key
            for key, messages
            in self._messages.items()
            if (
                not messages
                or messages[-1][0] < cutoff
            )
        ]

        for key in stale_keys:
            self._messages.pop(
                key,
                None,
            )

            self._last_text.pop(
                key,
                None,
            )


class AdminCache:
    """
    نتیجه بررسی ادمین را برای چند دقیقه نگه می‌دارد
    تا برای هر پیام مشکوک API call تکراری نزنیم.
    """

    TTL_SECONDS = 300
    MAX_ENTRIES = 5000

    def __init__(self) -> None:
        self._cache: dict[
            tuple[int, int],
            tuple[bool, float],
        ] = {}

    def get(
        self,
        group_id: int,
        user_id: int,
    ) -> Optional[bool]:
        entry = self._cache.get(
            (
                group_id,
                user_id,
            )
        )

        if entry is None:
            return None

        is_admin, cached_at = entry

        if (
            time.monotonic()
            - cached_at
            > self.TTL_SECONDS
        ):
            self._cache.pop(
                (
                    group_id,
                    user_id,
                ),
                None,
            )
            return None

        return is_admin

    def set(
        self,
        group_id: int,
        user_id: int,
        is_admin: bool,
    ) -> None:
        key = (
            group_id,
            user_id,
        )

        now = time.monotonic()

        if key not in self._cache:
            expired_keys = [
                cache_key
                for cache_key, (
                    _,
                    cached_at,
                )
                in self._cache.items()
                if (
                    now - cached_at
                    > self.TTL_SECONDS
                )
            ]

            for cache_key in expired_keys:
                self._cache.pop(
                    cache_key,
                    None,
                )

            if (
                len(self._cache)
                >= self.MAX_ENTRIES
            ):
                oldest_key = min(
                    self._cache,
                    key=lambda cache_key:
                    self._cache[
                        cache_key
                    ][1],
                )

                self._cache.pop(
                    oldest_key,
                    None,
                )

        self._cache[key] = (
            is_admin,
            now,
        )