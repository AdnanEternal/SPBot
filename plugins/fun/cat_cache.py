from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


MAX_CACHE_BYTES = 4 * 1024 * 1024
MAX_CACHE_IMAGES = 3


@dataclass(slots=True)
class CachedCat:
    key: str
    data: bytes
    filename: str


class CatCache:
    def __init__(
        self,
        *,
        max_bytes: int = MAX_CACHE_BYTES,
        max_images: int = MAX_CACHE_IMAGES,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_images = max_images

        self._items: list[CachedCat] = []
        self._used_keys: set[str] = set()
        self._selection_order: list[str] = []

        self._total_bytes = 0

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def count(self) -> int:
        return len(self._items)

    def add(self, data: bytes, filename: str) -> None:
        if not data:
            return

        key = hashlib.sha256(data).hexdigest()

        # عکس تکراری را دوباره وارد cache نکن.
        if any(item.key == key for item in self._items):
            return

        # اگر خودش از کل ظرفیت بزرگ‌تر است، cache نمی‌شود.
        if len(data) > self.max_bytes:
            return

        # تا جای لازم قدیمی‌ترین عکس‌ها را حذف کن.
        while (
            self._items
            and (
                len(self._items) >= self.max_images
                or self._total_bytes + len(data) > self.max_bytes
            )
        ):
            removed = self._items.pop(0)
            self._total_bytes -= len(removed.data)
            self._used_keys.discard(removed.key)

        item = CachedCat(
            key=key,
            data=data,
            filename=filename,
        )

        self._items.append(item)
        self._total_bytes += len(data)

        # چون مجموعه عوض شده، ترتیب انتخاب قبلی دیگر معتبر نیست.
        self._selection_order.clear()
        self._used_keys.clear()

    def get_random(self) -> CachedCat | None:
        if not self._items:
            return None

        # تا وقتی همه‌ی عکس‌ها یک بار انتخاب نشده‌اند،
        # عکس تکراری انتخاب نمی‌شود.
        available = [
            item
            for item in self._items
            if item.key not in self._used_keys
        ]

        if not available:
            self._used_keys.clear()
            available = list(self._items)

        selected = random.choice(available)
        self._used_keys.add(selected.key)

        return selected

    def remove(self, key: str) -> None:
        for index, item in enumerate(self._items):
            if item.key == key:
                self._items.pop(index)
                self._total_bytes -= len(item.data)
                self._used_keys.discard(key)
                break
