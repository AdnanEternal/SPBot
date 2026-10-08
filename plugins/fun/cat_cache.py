
from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass


MAX_CACHE_BYTES = 4 * 1024 * 1024
MAX_CACHE_IMAGES = 3

DebugLogger = Callable[[str, str], None]


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

    def _debug(
        self,
        debug: DebugLogger | None,
        category: str,
        message: str,
    ) -> None:
        if debug is not None:
            debug(category, message)

    def add(
        self,
        data: bytes,
        filename: str,
        *,
        debug: DebugLogger | None = None,
    ) -> None:
        if not data:
            self._debug(
                debug,
                "CACHE",
                "ADD ignored=empty_data",
            )
            return

        key = hashlib.sha256(data).hexdigest()

        if any(item.key == key for item in self._items):
            self._debug(
                debug,
                "CACHE",
                (
                    f"ADD result=DUPLICATE "
                    f"key={key[:8]} "
                    f"count={self.count} "
                    f"bytes={self.total_bytes}"
                ),
            )
            return

        if len(data) > self.max_bytes:
            self._debug(
                debug,
                "CACHE",
                (
                    f"ADD result=TOO_LARGE "
                    f"size={len(data)} "
                    f"limit={self.max_bytes}"
                ),
            )
            return

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

            self._debug(
                debug,
                "CACHE",
                (
                    f"EVICT "
                    f"key={removed.key[:8]} "
                    f"size={len(removed.data)} "
                    f"reason="
                    f"{'max_images' if len(self._items) >= self.max_images else 'max_bytes'}"
                ),
            )

        item = CachedCat(
            key=key,
            data=data,
            filename=filename,
        )

        self._items.append(item)
        self._total_bytes += len(data)

        self._selection_order.clear()
        self._used_keys.clear()

        self._debug(
            debug,
            "CACHE",
            (
                f"ADD result=ADDED "
                f"key={key[:8]} "
                f"file={filename} "
                f"size={len(data)} "
                f"count={self.count}/{self.max_images} "
                f"bytes={self.total_bytes}/{self.max_bytes}"
            ),
        )

    def get_random(
        self,
        *,
        debug: DebugLogger | None = None,
    ) -> CachedCat | None:
        if not self._items:
            self._debug(
                debug,
                "CACHE",
                "SELECT result=EMPTY",
            )
            return None

        available = [
            item
            for item in self._items
            if item.key not in self._used_keys
        ]

        if not available:
            self._debug(
                debug,
                "CACHE",
                "SELECT cycle=RESET reason=all_items_used",
            )

            self._used_keys.clear()
            available = list(self._items)

        selected = random.choice(available)
        self._used_keys.add(selected.key)

        self._debug(
            debug,
            "CACHE",
            (
                f"SELECT result=OK "
                f"key={selected.key[:8]} "
                f"file={selected.filename} "
                f"size={len(selected.data)} "
                f"remaining_in_cycle="
                f"{len(available) - 1}"
            ),
        )

        return selected

    def remove(
        self,
        key: str,
        *,
        debug: DebugLogger | None = None,
    ) -> None:
        for index, item in enumerate(self._items):
            if item.key == key:
                self._items.pop(index)
                self._total_bytes -= len(item.data)
                self._used_keys.discard(key)

                self._debug(
                    debug,
                    "CACHE",
                    (
                        f"REMOVE result=OK "
                        f"key={key[:8]} "
                        f"count={self.count} "
                        f"bytes={self.total_bytes}"
                    ),
                )
                return

        self._debug(
            debug,
            "CACHE",
            f"REMOVE result=NOT_FOUND key={key[:8]}",
        )
