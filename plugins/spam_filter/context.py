import re
import time

from core.ttl_cache import TTLCache

from .store import SpamContextStore


_URL_RE = re.compile(
    r"https?://\S+|www\.\S+|t\.me/\S+",
    re.IGNORECASE,
)

NEW_USER_HOURS = 24


class SpamContextProvider:
    PROFILE_CACHE_TTL = 600
    PROFILE_CACHE_MAX = 2048

    def __init__(
        self,
        store: SpamContextStore,
        client,
    ) -> None:
        self.store = store
        self.client = client

        self._profile_link_cache = TTLCache[
            tuple[int, int],
            bool,
        ](
            max_entries=self.PROFILE_CACHE_MAX,
            ttl_seconds=self.PROFILE_CACHE_TTL,
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

        self._profile_link_cache.delete(
            (
                group_id,
                user_id,
            )
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

        self._profile_link_cache.delete(
            (
                group_id,
                user_id,
            )
        )

    async def get_join_age(
        self,
        group_id: int,
        user_id: int,
    ) -> float | None:
        joined_at = await self.store.get_joined_at(
            group_id,
            user_id,
        )

        if joined_at is None:
            return None

        return max(
            0.0,
            time.time() - joined_at,
        )

    async def profile_has_link(
        self,
        event,
    ) -> bool:
        key = (
            event.chat_id,
            event.sender_id,
        )

        cached = self._profile_link_cache.get(
            key
        )

        if cached is not None:
            return cached

        try:
            sender = await event.get_sender()

        except Exception as exc:
            print(
                f"⚠️ دریافت پروفایل کاربر ناموفق بود: {exc}"
            )
            return False

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

        has_link = bool(
            _URL_RE.search(
                "\n".join(parts)
            )
        )

        self._profile_link_cache.set(
            key,
            has_link,
        )

        return has_link

    async def collect(
        self,
        event,
        external_signals: dict,
    ) -> dict:
        join_age = await self.get_join_age(
            event.chat_id,
            event.sender_id,
        )

        is_new_user = (
            join_age is not None
            and join_age
            <= NEW_USER_HOURS * 3600
        )

        return {
            "join_age_seconds": join_age,
            "is_new_user": is_new_user,
            "profile_has_link": (
                await self.profile_has_link(event)
                if is_new_user
                else False
            ),
            "external_signals": dict(
                external_signals
            ),
        }