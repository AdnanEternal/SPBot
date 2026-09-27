import time

from core.ttl_cache import TTLCache

from .store import (
    SpamContextStore,
    SpamRuleStore,
)


NEW_USER_HOURS = 24


class SpamContextProvider:
    PROFILE_CACHE_TTL = 600
    PROFILE_CACHE_MAX = 2048

    REFERENCE_TIME_CACHE_TTL = 900
    REFERENCE_TIME_CACHE_MAX = 2048

    def __init__(self, store, rules, client):
        self.store = store
        self.rules = rules
        self.client = client

        self._profile_cache = TTLCache[tuple[int, int], dict](
            max_entries=self.PROFILE_CACHE_MAX,
            ttl_seconds=self.PROFILE_CACHE_TTL,
        )

        self._reference_time_cache = TTLCache[tuple[int, int], float](
            max_entries=self.REFERENCE_TIME_CACHE_MAX,
            ttl_seconds=self.REFERENCE_TIME_CACHE_TTL,
        )

    async def record_first_seen(self, group_id: int, user_id: int) -> None:
        # اگه از قبل تو کش داریمش، یعنی ردیفش تو DB مطمئناً ساخته شده؛
        # لازم نیست دوباره select/insert بزنیم.
        if self._reference_time_cache.get((group_id, user_id)) is not None:
            return

        await self.store.ensure_first_seen(group_id, user_id, time.time())

    async def record_join(self, group_id: int, user_id: int) -> None:
        await self.store.set_joined_at(group_id, user_id, time.time())

        key = (group_id, user_id)
        self._profile_cache.delete(key)
        self._reference_time_cache.delete(key)

    async def record_leave(self, group_id: int, user_id: int) -> None:
        await self.store.clear_user(group_id, user_id)

        key = (group_id, user_id)
        self._profile_cache.delete(key)
        self._reference_time_cache.delete(key)

    async def get_join_age(self, group_id: int, user_id: int) -> float | None:
        key = (group_id, user_id)

        reference_time = self._reference_time_cache.get(key)

        if reference_time is None:
            reference_time = await self.store.get_reference_time(group_id, user_id)

            if reference_time is not None:
                self._reference_time_cache.set(key, reference_time)

        if reference_time is None:
            return None

        return max(0.0, time.time() - reference_time)