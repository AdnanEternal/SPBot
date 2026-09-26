import re
import time

from core.ttl_cache import TTLCache

from .detection import (
    extract_links,
    is_whitelisted_url,
)

from .store import (
    SpamContextStore,
    SpamLinkWhitelistStore,
    SpamRuleStore,
)


_URL_RE = re.compile(
    r"https?://[^\s]+|www\.[^\s]+|t\.me/[^\s]+",
    re.IGNORECASE,
)

# لینک عمومی پروفایل وب سروش پلاس:
# حساسیت نسبتاً بالا
_SPLUS_WEB_RE = re.compile(
    r"https?://(?:www\.)?web\.splus\.ir(?:[/?#]|$)",
    re.IGNORECASE,
)

# لینک Meet سروش پلاس:
# عمداً سیگنال بسیار ضعیف/خنثی
_SPLUS_MEET_RE = re.compile(
    r"https?://(?:www\.)?splus\.ir/meet(?:[/?#]|$)",
    re.IGNORECASE,
)

NEW_USER_HOURS = 24


class SpamContextProvider:
    PROFILE_CACHE_TTL = 600
    PROFILE_CACHE_MAX = 2048

    def __init__(
        self,
        store: SpamContextStore,
        rules: SpamRuleStore,
        link_whitelist: SpamLinkWhitelistStore,
        client,
) -> None:
        self.store = store
        self.rules = rules
        self.link_whitelist = link_whitelist
        self.client = client

        self._profile_cache = TTLCache[
            tuple[int, int],
            dict,
        ](
            max_entries=self.PROFILE_CACHE_MAX,
            ttl_seconds=self.PROFILE_CACHE_TTL,
        )



    def invalidate_profile_cache(self) -> None:
        self._profile_cache.clear()

    async def record_first_seen(
        self,
        group_id: int,
        user_id: int,
    ) -> None:
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

        self._profile_cache.delete(
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

        self._profile_cache.delete(
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
        reference_time = (
            await self.store.get_reference_time(
                group_id,
                user_id,
            )
        )

        if reference_time is None:
            return None

        return max(
            0.0,
            time.time() - reference_time,
        )

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
                f"⚠️ دریافت پروفایل کاربر ناموفق بود: {exc}"
            )

            return {
                "text": "",
                "has_link": False,
                "has_splus_web_link": False,
                "has_splus_meet_link": False,
                "has_other_link": False,
            }

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

        profile_text = "\n".join(parts)

        all_urls = extract_links(
            profile_text
        )

        whitelist = (
            await self.link_whitelist.get_all()
        )

        urls = [
            url
            for url in all_urls
            if not is_whitelisted_url(
                url,
                whitelist,
            )
        ]

        has_splus_web_link = any(
            _SPLUS_WEB_RE.search(url)
            for url in urls
        )

        has_splus_meet_link = any(
            _SPLUS_MEET_RE.search(url)
            for url in urls
        )

        # لینک‌های عادی همچنان سیگنال خودشان را حفظ می‌کنند،
        # ولی meet را از دسته‌ی لینک‌های مؤثر حذف می‌کنیم.
        has_other_link = any(
            not _SPLUS_WEB_RE.search(url)
            and not _SPLUS_MEET_RE.search(url)
            for url in urls
        )

        result = {
            "text": profile_text,

            # وجود هر نوع لینک در پروفایل
            "has_link": bool(urls),

            # لینک web.splus.ir
            "has_splus_web_link": (
                has_splus_web_link
            ),

            # لینک splus.ir/meet
            "has_splus_meet_link": (
                has_splus_meet_link
            ),

            # لینک‌های دیگر، به‌جز meet
            "has_other_link": (
                has_other_link
            ),
        }

        self._profile_cache.set(
            key,
            result,
        )

        return dict(result)

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

        matched_bio_rules = (
            await self.rules.match_bio(
                event.chat_id,
                profile["text"],
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

            "profile_has_link": (
                profile["has_link"]
            ),

            "profile_has_splus_web_link": (
                profile[
                    "has_splus_web_link"
                ]
            ),

            "profile_has_splus_meet_link": (
                profile[
                    "has_splus_meet_link"
                ]
            ),

            "profile_has_other_link": (
                profile[
                    "has_other_link"
                ]
            ),

            "matched_bio_rules": (
                matched_bio_rules
            ),

            "external_signals": dict(
                external_signals
            ),
        }