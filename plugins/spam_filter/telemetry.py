from collections import deque
import time


class SpamTelemetry:
    """
    ثبت موقت رفتارهای SUSPICIOUS.

    در دیتابیس ذخیره نمی‌شود؛ فقط برای مشاهده‌ی
    رفتار اخیر و تحلیل/debug مناسب است.
    """

    def __init__(
        self,
        max_entries: int = 1000,
    ) -> None:
        self._items = deque(
            maxlen=max_entries
        )

    def add(
        self,
        *,
        group_id: int,
        user_id: int,
        score: int,
        reason: str,
        hard_rule: str | None,
    ) -> None:
        self._items.append(
            {
                "time": time.time(),
                "group_id": group_id,
                "user_id": user_id,
                "score": score,
                "reason": reason,
                "hard_rule": hard_rule,
            }
        )

    def recent(
        self,
        limit: int = 100,
    ) -> list[dict]:
        if limit <= 0:
            return []

        return list(
            self._items
        )[-limit:]