import asyncio
import traceback

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

_admin_inflight: dict[
    tuple[str, int],
    asyncio.Future,
] = {}


async def _fetch_admin_ids(
    client,
    chat,
    key: tuple[str, int],
) -> frozenset[int] | None:

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

        ids = frozenset(
            participant.user_id
            for participant in participants
            if isinstance(
                participant,
                (
                    types.ChatParticipantCreator,
                    types.ChatParticipantAdmin,
                ),
            )
        )

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

        ids = frozenset(
            participant.user_id
            for participant in result.participants
            if getattr(
                participant,
                "user_id",
                None,
            ) is not None
        )

    else:
        return None

    _admin_cache.set(
        key,
        ids,
    )

    return ids


async def _get_admin_ids(
    client,
    chat,
) -> frozenset[int] | None:

    key = (
        type(chat).__name__,
        chat.id,
    )

    cached = _admin_cache.get(key)

    if cached is not None:
        return cached

    existing = _admin_inflight.get(key)

    if existing is not None:
        return await asyncio.shield(
            existing
        )

    future = asyncio.ensure_future(
        _fetch_admin_ids(
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

    future.add_done_callback(cleanup)

    return await asyncio.shield(future)


async def is_chat_admin(
    client,
    chat,
    sender_id,
    *,
    raise_on_error: bool = False,
) -> bool:

    if sender_id is None:
        return False

    try:
        admin_ids = await asyncio.wait_for(
            _get_admin_ids(
                client,
                chat,
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


def is_owner(
    sender_id: int,
) -> bool:
    if sender_id is None:
        return False

    owner_id = config.get(
        "BOT_OWNERS_ID",
        "",
    )

    if not owner_id:
        return False

    owner_ids = {
        int(user_id.strip())
        for user_id in owner_id.split(",")
        if user_id.strip().isdigit()
    }

    return sender_id in owner_ids