from typing import TYPE_CHECKING

from splusthon import events
from splusthon.tl import functions, types

from core.decorators import command, on_event
from core.permissions import (
    get_admins,
    is_chat_admin,
)
from core.time_manager import format_project_time

if TYPE_CHECKING:
    from .plugin import GroupManagerPlugin

async def _get_restricted_and_banned_counts(
    client,
    chat,
) -> tuple[int | None, int | None]:

    # این فیلترها برای Supergroup / Channel هستند.
    if not isinstance(
        chat,
        types.Channel,
    ):
        return None, None

    try:
        restricted_result = await client(
            functions.channels.GetParticipantsRequest(
                channel=chat,
                filter=types.ChannelParticipantsBanned(
                    q=""
                ),
                offset=0,
                limit=1,
                hash=0,
            )
        )

        banned_result = await client(
            functions.channels.GetParticipantsRequest(
                channel=chat,
                filter=types.ChannelParticipantsKicked(
                    q=""
                ),
                offset=0,
                limit=1,
                hash=0,
            )
        )

    except Exception:
        import traceback

        print(
            "⚠️ دریافت تعداد کاربران "
            "محدود و مسدودشده ناموفق بود:"
        )
        traceback.print_exc()

        return None, None

    restricted_count = getattr(
        restricted_result,
        "count",
        None,
    )

    banned_count = getattr(
        banned_result,
        "count",
        None,
    )

    return (
        restricted_count,
        banned_count,
    )

async def _get_group_creation_date(
    client,
    chat,
):
    try:
        first_message = await client.get_messages(
            chat,
            ids=1,
        )

    except Exception:
        return None

    if first_message is None:
        return None

    action = getattr(
        first_message,
        "action",
        None,
    )

    if isinstance(
        action,
        types.MessageActionChatCreate,
    ):
        return first_message.date

    return None


def _get_member_count(
    chat_full,
    chat,
) -> int | None:

    # Supergroup / Channel
    if isinstance(
        chat,
        types.Channel,
    ):
        return getattr(
            chat_full,
            "participants_count",
            None,
        )

    # Basic Group
    participants = getattr(
        chat_full,
        "participants",
        None,
    )

    participant_list = getattr(
        participants,
        "participants",
        None,
    )

    if participant_list is not None:
        return len(
            participant_list
        )

    return None


def _get_reaction_count(
    chat_full,
):
    available_reactions = getattr(
        chat_full,
        "available_reactions",
        None,
    )

    if available_reactions is None:
        return 0

    reactions = getattr(
        available_reactions,
        "reactions",
        None,
    )

    if reactions is None:
        # مثلاً ChatReactionsAll
        return "همه"

    return len(reactions)


async def _get_message_count(
    client,
    chat,
) -> int | None:

    try:
        result = await client(
            functions.messages.GetHistoryRequest(
                peer=chat,
                offset_id=0,
                offset_date=None,
                add_offset=0,
                limit=1,
                max_id=0,
                min_id=0,
                hash=0,
            )
        )

    except Exception:
        return None

    return getattr(
        result,
        "count",
        None,
    )


def _is_group_stats_shortcut(
    text: str,
) -> bool:

    normalized = "".join(
        (text or "").split()
    )

    return normalized in {
        "امارگروه",
        "گروهامار",
        "آمارگروه",
        "گروهآمار",
    }


@command(
    name="آمار گروه",
    permission="admin",
    chat_type="group",
    description="آمار و اطلاعات گروه را نشان می‌دهد.",
)
async def group_stats(
    self: "GroupManagerPlugin",
    event: events.NewMessage.Event,
) -> None:

    try:
        chat = await event.get_chat()

        # -------------------------------------------------
        # دریافت اطلاعات کامل گروه
        # -------------------------------------------------

        if isinstance(
            chat,
            types.Chat,
        ):
            result = await self.client(
                functions.messages.GetFullChatRequest(
                    chat.id
                )
            )

            chat_full = (
                result
                .full_chat
            )

        elif isinstance(
            chat,
            types.Channel,
        ):
            result = await self.client(
                functions.channels.GetFullChannelRequest(
                    channel=chat
                )
            )

            chat_full = (
                result
                .full_chat
            )


        else:
            await event.reply(
                "❌ این چت برای دریافت آمار گروه پشتیبانی نمی‌شود."
            )
            return

        # -------------------------------------------------
        # ADMIN COUNT
        # -------------------------------------------------

        admins = await get_admins(
            self.client,
            chat,
            force_refresh=False,
        )

        restricted_count, banned_count = (
            await _get_restricted_and_banned_counts(
                self.client,
                chat,
            )
        )

        admin_count = (
            len(admins)
            if admins is not None
            else None
        )

        # -------------------------------------------------
        # MEMBER COUNT
        # -------------------------------------------------

        member_count = _get_member_count(
            chat_full,
            chat,
        )

        normal_member_count = None

        if (
            member_count is not None
            and admin_count is not None
        ):
            normal_member_count = max(
                0,
                member_count
                - admin_count,
            )

        # -------------------------------------------------
        # MESSAGE COUNT
        # -------------------------------------------------

        message_count = await _get_message_count(
            self.client,
            chat,
        )

        # -------------------------------------------------
        # CREATION DATE
        # -------------------------------------------------

        creation_date = await _get_group_creation_date(
            self.client,
            chat,
        )

        # -------------------------------------------------
        # REACTIONS
        # -------------------------------------------------

        reaction_count = _get_reaction_count(
            chat_full
        )

        # -------------------------------------------------
        # BUILD RESPONSE
        # -------------------------------------------------

        lines = [
            "📊 آمار گروه",
            "",
        ]

        if creation_date is not None:
            lines.append(
                "📅 تاریخ ساخت: "
                + format_project_time(
                    creation_date,
                    "%Y/%m/%d",
                )
            )

            lines.append(
                "🕒 ساعت ساخت: "
                + format_project_time(
                    creation_date,
                    "%H:%M:%S",
                )
            )
        else:
            lines.append(
                "📅 تاریخ ساخت: نامشخص"
            )

        lines.extend([
            "",
            (
                "👥 کل اعضا: "
                f"{member_count:,}"
                if member_count is not None
                else
                "👥 کل اعضا: نامشخص"
            ),
            (
                "👑 ادمین‌ها: "
                f"{admin_count:,}"
                if admin_count is not None
                else
                "👑 ادمین‌ها: نامشخص"
            ),
            (
                "🙂 اعضای عادی: "
                f"{normal_member_count:,}"
                if normal_member_count is not None
                else
                "🙂 اعضای عادی: نامشخص"
            ),
                (
                "🔇 محدود/میوت‌شده‌ها: "
                f"{restricted_count:,}"
                if restricted_count is not None
                else
                "🔇 محدود/میوت‌شده‌ها: نامشخص"
            ),
            (
                "🚫 مسدودشده‌ها: "
                f"{banned_count:,}"
                if banned_count is not None
                else
                "🚫 مسدودشده‌ها: نامشخص"
            ),

            (
                "💬 تعداد پیام‌ها: "
                f"{message_count:,}"
                if message_count is not None
                else
                "💬 تعداد پیام‌ها: نامشخص"
            ),
            (
                "👍 واکنش‌های مجاز: "
                f"{reaction_count}/50"
            ),
        ])

        await event.reply(
            "\n".join(lines)
        )

    except Exception:
        import traceback

        print(
            "❌ خطا در دریافت آمار گروه:"
        )
        traceback.print_exc()

        await event.reply(
            "❌ دریافت آمار گروه ناموفق بود."
        )


        
@on_event(events.NewMessage(incoming=True))
async def on_message(
    self: "GroupManagerPlugin",
    event: events.NewMessage.Event,
) -> None:

    if not event.is_group:
        return

    if not _is_group_stats_shortcut(
        event.raw_text or ""
    ):
        return

    chat = await event.get_chat()

    if not await is_chat_admin(
        self.client,
        chat,
        event.sender_id,
    ):
        return

    await self.group_stats(
        event
    )