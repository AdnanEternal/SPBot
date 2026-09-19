from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    """
    Cache ساده و محدود برای داده‌های کوتاه‌مدت.

    ویژگی‌ها:
    - TTL برای حذف داده‌های قدیمی
    - سقف تعداد آیتم‌ها
    - LRU برای بیرون انداختن قدیمی‌ترین آیتم
    - بدون asyncio و lock؛ چون فقط داخل event loop استفاده می‌شود
    """

    def __init__(
        self,
        max_entries: int,
        ttl_seconds: float,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than 0")

        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than 0")

        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

        self._data: OrderedDict[
            K,
            tuple[float, V],
        ] = OrderedDict()

    def get(self, key: K) -> V | None:
        entry = self._data.get(key)

        if entry is None:
            return None

        cached_at, value = entry

        if time.monotonic() - cached_at >= self.ttl_seconds:
            self._data.pop(key, None)
            return None

        self._data.move_to_end(key)

        return value

    def set(
        self,
        key: K,
        value: V,
    ) -> None:
        self._data[key] = (
            time.monotonic(),
            value,
        )

        self._data.move_to_end(key)

        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def delete(self, key: K) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)