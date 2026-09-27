from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.ttl_cache import TTLCache


NEW_USER_MAX_AGE_SECONDS = 60 * 60
MIN_CLEAN_STREAK_TO_ESTABLISH = 5

DEFAULT_NEW_TRUST = 0.0
DEFAULT_LEGACY_TRUST = 20.0

CLEAN_TRUST_GAIN = 1.0
VIOLATION_TRUST_LOSS_PER_SEVERITY = 4.0

PERSIST_CLEAN_EVERY = 5


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
    if origin == "LEGACY_OR_UNKNOWN":
        return "LEGACY"

    if join_age_seconds is None:
        return "UNKNOWN"

    if (
        join_age_seconds < NEW_USER_MAX_AGE_SECONDS
        and clean_streak < MIN_CLEAN_STREAK_TO_ESTABLISH
    ):
        return "NEW"

    return "ESTABLISHED"


class SpamTrustManager:
    CACHE_MAX_ENTRIES = 5000
    CACHE_TTL_SECONDS = 3600

    def __init__(
        self,
        store,
    ) -> None:
        self.store = store

        self._cache = TTLCache[
            tuple[int, int],
            SpamTrustState,
        ](
            max_entries=self.CACHE_MAX_ENTRIES,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

        self._dirty = TTLCache[
            tuple[int, int],
            SpamTrustState,
        ](
            max_entries=self.CACHE_MAX_ENTRIES,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

        self._pending_clean: dict[
            tuple[int, int],
            int,
        ] = {}

    async def get(
        self,
        group_id: int,
        user_id: int,
        origin: str,
    ) -> SpamTrustState:

        key = (
            group_id,
            user_id,
        )

        dirty = self._dirty.get(key)

        if dirty is not None:
            return SpamTrustState(
                trust_score=dirty.trust_score,
                clean_messages=dirty.clean_messages,
                clean_streak=dirty.clean_streak,
                suspicious_events=dirty.suspicious_events,
                violation_count=dirty.violation_count,
            )

        cached = self._cache.get(key)

        if cached is not None:
            return SpamTrustState(
                trust_score=cached.trust_score,
                clean_messages=cached.clean_messages,
                clean_streak=cached.clean_streak,
                suspicious_events=cached.suspicious_events,
                violation_count=cached.violation_count,
            )

        row = await self.store.get(
            group_id,
            user_id,
        )

        if row is None:
            trust_score = (
                DEFAULT_LEGACY_TRUST
                if origin == "LEGACY_OR_UNKNOWN"
                else DEFAULT_NEW_TRUST
            )

            state = SpamTrustState(
                trust_score=trust_score,
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
            state = SpamTrustState(
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

        self._cache.set(
            key,
            state,
        )

        return SpamTrustState(
            trust_score=state.trust_score,
            clean_messages=state.clean_messages,
            clean_streak=state.clean_streak,
            suspicious_events=state.suspicious_events,
            violation_count=state.violation_count,
        )

    async def record_clean(
        self,
        group_id: int,
        user_id: int,
        state: SpamTrustState,
    ) -> SpamTrustState:

        key = (
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

        self._cache.set(
            key,
            state,
        )

        self._dirty.set(
            key,
            state,
        )

        pending = (
            self._pending_clean.get(
                key,
                0,
            )
            + 1
        )

        self._pending_clean[key] = pending

        if pending >= PERSIST_CLEAN_EVERY:
            await self.store.save(
                group_id,
                user_id,
                state,
            )

            self._dirty.delete(key)
            self._pending_clean.pop(
                key,
                None,
            )

        return state

    async def record_suspicious(
        self,
        group_id: int,
        user_id: int,
        state: SpamTrustState,
    ) -> SpamTrustState:

        key = (
            group_id,
            user_id,
        )

        state.suspicious_events += 1

        # Suspicious is not a confirmed violation,
        # so trust does not decrease.
        state.clean_streak = 0

        await self.store.save(
            group_id,
            user_id,
            state,
        )

        self._cache.set(
            key,
            state,
        )

        self._dirty.delete(key)
        self._pending_clean.pop(
            key,
            None,
        )

        return state

    async def record_violation(
        self,
        group_id: int,
        user_id: int,
        state: SpamTrustState,
        severity: int,
    ) -> SpamTrustState:

        key = (
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

        self._cache.set(
            key,
            state,
        )

        self._dirty.delete(key)
        self._pending_clean.pop(
            key,
            None,
        )

        return state

    async def flush(self) -> None:
        dirty_items = list(
            self._dirty._data.items()
        )

        for key, (_, state) in dirty_items:
            group_id, user_id = key

            await self.store.save(
                group_id,
                user_id,
                state,
            )

            self._dirty.delete(key)
            self._pending_clean.pop(
                key,
                None,
            )