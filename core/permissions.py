import asyncio
import traceback
from dataclasses import dataclass
from typing import Any

from splusthon.tl import functions, types

from config import config
from core.ttl_cache import TTLCache


ADMIN_CACHE_TTL = 120


_admin_cache = TTLCache[
    tuple[str, int],
    frozenset[int],
](
    max_entries=1024,
    ttl_seconds=ADMIN_CACHE_TTL,
)


_admin_details_cache = TTLCache[
    tuple[str, int],
    tuple["AdminInfo", ...],
](
    max_entries=1024,
    ttl_seconds=ADMIN_CACHE_TTL,
)


_admin_inflight: dict[
    tuple[str, int],
    asyncio.Future,
] = {}


@dataclass(frozen=True, slots=True)
class AdminInfo:
    user_id: int
    entity: Any
    title: str


def _participant_title(
    participant,
) -> str:

    # بعضی نوع‌های ادمین/مالک ممکنه rank داشته باشند.
    rank = (
        getattr(
            participant,
            "rank",
            None,
        )
        or ""
    ).strip()

    if rank:
        return rank

    if isinstance(
        participant,
        types.ChatParticipantCreator,
    ):
        return "مالک"

    if isinstance(
        participant,
        types.ChannelParticipantCreator,
    ):
        return "مالک"

    return "ادمین"


async def _fetch_admins(
    client,
    chat,
    key: tuple[str, int],
) -> tuple[AdminInfo, ...] | None:

    # -------------------------------------------------
    # BASIC GROUP
    # -------------------------------------------------

    if isinstance(chat, types.Chat):

        full_chat = await client(
            functions.messages.GetFullChatRequest(
                chat.id
            )
        )

        participants = (
            full_chat
            .full_chat
            .participants
            .participants
        )

        admin_participants = [
            participant
            for participant in participants
            if isinstance(
                participant,
                (
                    types.ChatParticipantCreator,
                    types.ChatParticipantAdmin,
                ),
            )
        ]

        users = full_chat.users

    # -------------------------------------------------
    # SUPERGROUP / CHANNEL
    # -------------------------------------------------

    elif isinstance(chat, types.Channel):

        result = await client(
            functions.channels.GetParticipantsRequest(
                channel=chat,
                filter=types.ChannelParticipantsAdmins(),
                offset=0,
                limit=200,
                hash=0,
            )
        )

        admin_participants = [
            participant
            for participant in result.participants
            if isinstance(
                participant,
                (
                    types.ChannelParticipantCreator,
                    types.ChannelParticipantAdmin,
                ),
            )
        ]

        users = result.users

    else:
        return None

    # -------------------------------------------------
    # MAP USER ENTITIES
    # -------------------------------------------------

    user_map = {
        user.id: user
        for user in users
    }

    admins: list[AdminInfo] = []

    for participant in admin_participants:

        user_id = getattr(
            participant,
            "user_id",
            None,
        )

        if user_id is None:
            continue

        entity = user_map.get(
            user_id
        )

        # در حالت عادی entity باید داخل همان response باشد.
        # فقط اگر نبود، یک fallback داریم.
        if entity is None:

            try:
                entity = await client.get_entity(
                    user_id
                )

            except Exception:
                entity = None

        if entity is None:
            continue

        admins.append(
            AdminInfo(
                user_id=user_id,
                entity=entity,
                title=_participant_title(
                    participant
                ),
            )
        )

    # -------------------------------------------------
    # UPDATE CACHES
    # -------------------------------------------------

    admin_infos = tuple(admins)

    admin_ids = frozenset(
        admin.user_id
        for admin in admin_infos
    )

    _admin_cache.set(
        key,
        admin_ids,
    )

    _admin_details_cache.set(
        key,
        admin_infos,
    )

    return admin_infos


async def get_admins(
    client,
    chat,
    *,
    force_refresh: bool = False,
) -> tuple[AdminInfo, ...] | None:

    key = (
        type(chat).__name__,
        chat.id,
    )

    # در حالت عادی از cache استفاده کن.
    if not force_refresh:

        cached = _admin_details_cache.get(
            key
        )

        if cached is not None:
            return cached

    # اگر همزمان چند درخواست برای همین گروه آمد،
    # فقط یکی API را صدا بزند.
    existing = _admin_inflight.get(
        key
    )

    if existing is not None:
        return await asyncio.shield(
            existing
        )

    future = asyncio.ensure_future(
        _fetch_admins(
            client,
            chat,
            key,
        )
    )

    _admin_inflight[key] = future

    def cleanup(
        _future,
        cache_key=key,
    ):
        _admin_inflight.pop(
            cache_key,
            None,
        )

    future.add_done_callback(
        cleanup
    )

    return await asyncio.shield(
        future
    )




async def _get_admin_ids(
    client,
    chat,
    *,
    force_refresh: bool = False,
) -> frozenset[int] | None:

    admins = await get_admins(
        client,
        chat,
        force_refresh=force_refresh,
    )
    
    if admins is None:
        return None

    return frozenset(
        admin.user_id
        for admin in admins
    )


async def is_chat_admin(
    client,
    chat,
    sender_id,
    *,
    raise_on_error: bool = False,
    force_refresh: bool = False,
) -> bool:

    if sender_id is None:
        return False

    try:
        admin_ids = await asyncio.wait_for(
            _get_admin_ids(
                client,
                chat,
                force_refresh=force_refresh,
            ),
            timeout=15,
        )

        return (
            admin_ids is not None
            and sender_id in admin_ids
        )

    except asyncio.TimeoutError:

        print(
            "⚠️ بررسی ادمین Timeout شد."
        )

        if raise_on_error:
            raise

        return False

    except Exception:

        print(
            "❌ خطا در بررسی دسترسی ادمین:"
        )
        traceback.print_exc()

        if raise_on_error:
            raise

        return False


def owner_ids() -> frozenset[int]:
    raw = config.get(
        "BOT_OWNERS_ID",
        "",
    )

    return frozenset(
        int(x.strip())
        for x in raw.split(",")
        if x.strip().isdigit()
    )


def is_owner(
    sender_id: int,
) -> bool:

    return (
        sender_id is not None
        and sender_id in owner_ids()
    )