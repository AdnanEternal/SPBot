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
    """
    اطلاعاتی که Spam Engine از خود رفتار پیام استخراج نمی‌کند.

    شامل:
    - زمان عضویت
    - تازه‌وارد بودن
    - وضعیت لینک موجود در پروفایل
    - signalهای خارجی
    """

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

        self._profile_link_cache.pop(
            (
                group_id,
                user_id,
            ),
            None,
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

        self._profile_link_cache.pop(
            (
                group_id,
                user_id,
            ),
            None,
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

        age = (
            time.time()
            - joined_at
        )

        return max(
            0.0,
            age,
        )

    async def is_new_user(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        age = await self.get_join_age(
            group_id,
            user_id,
        )

        if age is None:
            return False

        return (
            age
            <= NEW_USER_HOURS * 3600
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

        profile_text_parts = []

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
                profile_text_parts.append(
                    value
                )

        profile_text = "\n".join(
            profile_text_parts
        )

        has_link = bool(
            _URL_RE.search(
                profile_text
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

        return {
            "join_age_seconds": join_age,
            "is_new_user": (
                join_age is not None
                and join_age
                <= NEW_USER_HOURS * 3600
            ),
            "profile_has_link": await self.profile_has_link(
                event
            ),
            "external_signals": dict(
                external_signals
            ),
        }