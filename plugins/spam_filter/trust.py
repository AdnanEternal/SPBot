from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass


NEW_USER_MAX_AGE_SECONDS = 60 * 60
MIN_CLEAN_STREAK_TO_ESTABLISH = 5

DEFAULT_TRUST_SCORE = 0.0

CLEAN_TRUST_GAIN = 1.0
VIOLATION_TRUST_LOSS_PER_SEVERITY = 4.0

PERSIST_EVERY = 5

CACHE_MAX_ENTRIES = 5000
DIRTY_MAX_ENTRIES = 5000


@dataclass(slots=True)
class SpamTrustState:
    trust_score: float
    clean_messages: int
    clean_streak: int
    suspicious_events: int
    violation_count: int


def classify_user_state(
    *,
    join_age_seconds: float | None,
    origin: str,
    clean_streak: int,
) -> str:
    if join_age_seconds is None:
        return "UNKNOWN"

    if (
        join_age_seconds
        < NEW_USER_MAX_AGE_SECONDS
        and clean_streak
        < MIN_CLEAN_STREAK_TO_ESTABLISH
    ):
        return "NEW"

    return "ESTABLISHED"


class SpamTrustManager:
    def __init__(
        self,
        store,
    ) -> None:
        self.store = store

        self._cache: OrderedDict[
            tuple[int, int],
            SpamTrustState,
        ] = OrderedDict()

        self._dirty: OrderedDict[
            tuple[int, int],
            SpamTrustState,
        ] = OrderedDict()

        self._pending: dict[
            tuple[int, int],
            int,
        ] = {}

        # Makes trust updates atomic when several
        # messages from the same user arrive together.
        self._lock = asyncio.Lock()

    @staticmethod
    def _copy_state(
        state: SpamTrustState,
    ) -> SpamTrustState:
        return SpamTrustState(
            trust_score=state.trust_score,
            clean_messages=state.clean_messages,
            clean_streak=state.clean_streak,
            suspicious_events=state.suspicious_events,
            violation_count=state.violation_count,
        )

    @staticmethod
    def _from_row(
        row,
    ) -> SpamTrustState:
        return SpamTrustState(
            trust_score=float(
                row["trust_score"]
            ),
            clean_messages=int(
                row["clean_messages"]
            ),
            clean_streak=int(
                row["clean_streak"]
            ),
            suspicious_events=int(
                row["suspicious_events"]
            ),
            violation_count=int(
                row["violation_count"]
            ),
        )

    def _cache_set(
        self,
        key: tuple[int, int],
        state: SpamTrustState,
    ) -> None:
        self._cache[key] = state
        self._cache.move_to_end(key)

        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(
                last=False
            )

    def _dirty_set(
        self,
        key: tuple[int, int],
        state: SpamTrustState,
    ) -> None:
        self._dirty[key] = (
            self._copy_state(state)
        )
        self._dirty.move_to_end(key)

    async def _get_or_create_unlocked(
        self,
        group_id: int,
        user_id: int,
    ) -> SpamTrustState:

        key = (
            group_id,
            user_id,
        )

        dirty = self._dirty.get(key)

        if dirty is not None:
            return self._copy_state(
                dirty
            )

        cached = self._cache.get(key)

        if cached is not None:
            self._cache.move_to_end(key)

            return self._copy_state(
                cached
            )

        row = await self.store.get(
            group_id,
            user_id,
        )

        if row is None:
            state = SpamTrustState(
                trust_score=DEFAULT_TRUST_SCORE,
                clean_messages=0,
                clean_streak=0,
                suspicious_events=0,
                violation_count=0,
            )

            await self.store.save(
                group_id,
                user_id,
                state,
            )

        else:
            state = self._from_row(row)

        self._cache_set(
            key,
            state,
        )

        return self._copy_state(
            state
        )

    async def get(
        self,
        group_id: int,
        user_id: int,
    ) -> SpamTrustState:

        async with self._lock:
            return await self._get_or_create_unlocked(
                group_id,
                user_id,
            )

    async def record_clean(
        self,
        group_id: int,
        user_id: int,
    ) -> SpamTrustState:

        async with self._lock:
            key = (
                group_id,
                user_id,
            )

            state = await self._get_or_create_unlocked(
                group_id,
                user_id,
            )

            state.clean_messages += 1
            state.clean_streak += 1

            state.trust_score = min(
                100.0,
                state.trust_score
                + CLEAN_TRUST_GAIN,
            )

            self._cache_set(
                key,
                state,
            )

            pending = (
                self._pending.get(
                    key,
                    0,
                )
                + 1
            )

            self._pending[key] = pending

            self._dirty_set(
                key,
                state,
            )

            if pending >= PERSIST_EVERY:
                await self.store.save(
                    group_id,
                    user_id,
                    state,
                )

                self._dirty.pop(
                    key,
                    None,
                )

                self._pending.pop(
                    key,
                    None,
                )

            elif len(self._dirty) > DIRTY_MAX_ENTRIES:
                old_key, old_state = (
                    self._dirty.popitem(
                        last=False
                    )
                )

                await self.store.save(
                    old_key[0],
                    old_key[1],
                    old_state,
                )

                self._pending.pop(
                    old_key,
                    None,
                )

            return self._copy_state(
                state
            )

    async def record_suspicious(
        self,
        group_id: int,
        user_id: int,
    ) -> SpamTrustState:

        async with self._lock:
            key = (
                group_id,
                user_id,
            )

            state = await self._get_or_create_unlocked(
                group_id,
                user_id,
            )

            state.suspicious_events += 1

            # Suspicion is not a confirmed violation.
            # Trust does not decrease.
            state.clean_streak = 0

            self._cache_set(
                key,
                state,
            )

            pending = (
                self._pending.get(
                    key,
                    0,
                )
                + 1
            )

            self._pending[key] = pending

            self._dirty_set(
                key,
                state,
            )

            if pending >= PERSIST_EVERY:
                await self.store.save(
                    group_id,
                    user_id,
                    state,
                )

                self._dirty.pop(
                    key,
                    None,
                )

                self._pending.pop(
                    key,
                    None,
                )

            return self._copy_state(
                state
            )

    async def record_violation(
        self,
        group_id: int,
        user_id: int,
        severity: int,
    ) -> SpamTrustState:

        async with self._lock:
            key = (
                group_id,
                user_id,
            )

            state = await self._get_or_create_unlocked(
                group_id,
                user_id,
            )

            severity = max(
                0,
                min(
                    10,
                    int(severity),
                ),
            )

            state.violation_count += 1
            state.clean_streak = 0

            state.trust_score = max(
                0.0,
                state.trust_score
                - (
                    severity
                    * VIOLATION_TRUST_LOSS_PER_SEVERITY
                ),
            )

            await self.store.save(
                group_id,
                user_id,
                state,
            )

            self._cache_set(
                key,
                state,
            )

            self._dirty.pop(
                key,
                None,
            )

            self._pending.pop(
                key,
                None,
            )

            return self._copy_state(
                state
            )

    async def reset_clean_streak(
        self,
        group_id: int,
        user_id: int,
    ) -> None:

        async with self._lock:
            key = (
                group_id,
                user_id,
            )

            cached = self._cache.get(key)

            if cached is not None:
                state = self._copy_state(
                    cached
                )

            else:
                row = await self.store.get(
                    group_id,
                    user_id,
                )

                if row is None:
                    return

                state = self._from_row(row)

            if state.clean_streak == 0:
                return

            state.clean_streak = 0

            await self.store.save(
                group_id,
                user_id,
                state,
            )

            self._cache_set(
                key,
                state,
            )

            self._dirty.pop(
                key,
                None,
            )

            self._pending.pop(
                key,
                None,
            )

    async def flush(self) -> None:
        async with self._lock:
            dirty_items = list(
                self._dirty.items()
            )

            for key, state in dirty_items:
                await self.store.save(
                    key[0],
                    key[1],
                    state,
                )

            self._dirty.clear()
            self._pending.clear()