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

    def __init__(
        self,
        store,
        rules,
        client,
    ):
        self.store = store
        self.rules = rules
        self.client = client

        self._profile_cache = TTLCache[
            tuple[int, int],
            dict,
        ](
            max_entries=self.PROFILE_CACHE_MAX,
            ttl_seconds=self.PROFILE_CACHE_TTL,
        )

        self._reference_time_cache = TTLCache[
            tuple[int, int],
            tuple[float, str],
        ](
            max_entries=self.REFERENCE_TIME_CACHE_MAX,
            ttl_seconds=self.REFERENCE_TIME_CACHE_TTL,
        )

    async def get_membership_context(
        self,
        group_id: int,
        user_id: int,
    ) -> tuple[float | None, str]:

        key = (
            group_id,
            user_id,
        )

        cached = self._reference_time_cache.get(
            key
        )

        if cached is not None:
            reference_time, origin = cached

            return (
                max(
                    0.0,
                    time.time() - reference_time,
                ),
                origin,
            )

        row = await self.store.get_timing(
            group_id,
            user_id,
        )

        if row is None:
            return None, "UNKNOWN"

        joined_at = row["joined_at"]
        first_seen_at = row["first_seen_at"]

        if joined_at is not None:
            reference_time = float(
                joined_at
            )

            origin = "JOIN_OBSERVED"

        elif first_seen_at is not None:
            reference_time = float(
                first_seen_at
            )

            origin = "LEGACY_OR_UNKNOWN"

        else:
            return None, "UNKNOWN"

        self._reference_time_cache.set(
            key,
            (
                reference_time,
                origin,
            ),
        )

        return (
            max(
                0.0,
                time.time() - reference_time,
            ),
            origin,
        )


    async def record_first_seen(
        self,
        group_id: int,
        user_id: int,
    ) -> None:
        key = (
            group_id,
            user_id,
        )

        if (
            self._reference_time_cache.get(key)
            is not None
        ):
            return

        await self.store.ensure_first_seen(
            group_id,
            user_id,
            time.time(),
        )

    async def record_join(
        self,
        group_id: int,
        user_id: int,
    ) -> None:
        await self.store.set_joined_at(
            group_id,
            user_id,
            time.time(),
        )

        key = (
            group_id,
            user_id,
        )

        self._profile_cache.delete(
            key
        )

        self._reference_time_cache.delete(
            key
        )

    async def record_leave(
        self,
        group_id: int,
        user_id: int,
    ) -> None:
        await self.store.clear_user(
            group_id,
            user_id,
        )

        key = (
            group_id,
            user_id,
        )

        self._profile_cache.delete(
            key
        )

        self._reference_time_cache.delete(
            key
        )

    async def get_join_age(
        self,
        group_id: int,
        user_id: int,
    ) -> float | None:

        age, _ = await self.get_membership_context(
            group_id,
            user_id,
        )

        return age
    
    async def get_profile(
        self,
        event,
    ) -> dict:
        key = (
            event.chat_id,
            event.sender_id,
        )

        cached = self._profile_cache.get(
            key
        )

        if cached is not None:
            return dict(cached)

        try:
            sender = await event.get_sender()

        except Exception as exc:
            print(
                f"[SpamFilter][PROFILE] "
                f"status=failed "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )

            result = {
                "text": "",
            }

            self._profile_cache.set(
                key,
                result,
            )

            return dict(result)

        parts = []

        for attribute in (
            "about",
            "bio",
            "description",
            "website",
        ):
            value = getattr(
                sender,
                attribute,
                None,
            )

            if isinstance(value, str):
                parts.append(value)

        result = {
            "text": "\n".join(parts),
        }

        self._profile_cache.set(
            key,
            result,
        )

        return dict(result)

    def invalidate_profile_cache(
        self,
        group_id: int | None = None,
        user_id: int | None = None,
    ) -> None:
        if (
            group_id is not None
            and user_id is not None
        ):
            self._profile_cache.delete(
                (
                    group_id,
                    user_id,
                )
            )
            return

        self._profile_cache.clear()

    async def collect(
        self,
        event,
        external_signals: dict,
    ) -> dict:
        join_age = (
            await self.get_join_age(
                event.chat_id,
                event.sender_id,
            )
        )

        profile = await self.get_profile(
            event
        )

        matched_rules = (
            await self.rules.match_texts(
                event.chat_id,
                [
                    (
                        "message",
                        event.raw_text or "",
                    ),
                    (
                        "profile",
                        profile["text"],
                    ),
                ],
            )
        )

        is_new_user = (
            join_age is not None
            and join_age
            <= NEW_USER_HOURS * 3600
        )

        return {
            "join_age_seconds": join_age,
            "is_new_user": is_new_user,
            "profile_text": profile["text"],
            "matched_text_rules": matched_rules,
            "external_signals": dict(
                external_signals
            ),
        }


    