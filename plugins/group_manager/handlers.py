import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from splusthon import events
from splusthon.tl import functions, types

from core.decorators import command, on_event
from core.permissions import (
    get_admins,
    is_chat_admin,
)
from core.time_manager import (
    format_project_jalali_date,
    format_project_time,
)

if TYPE_CHECKING:
    from .plugin import GroupManagerPlugin





def _build_message_link(
    chat,
    message_id: int,
) -> str:
    """
    ساخت لینک وب پیام سروش‌پلاس بر اساس شناسه پیام.

    Public:
        https://splus.ir/<username>/<message_id>

    Private:
        https://splus.ir/c/<chat_id>/<message_id>
    """

    message_id = int(message_id)

    username = (
        getattr(
            chat,
            "username",
            None,
        )
        or ""
    ).strip()

    if username:
        return (
            f"https://splus.ir/"
            f"{username}/"
            f"{message_id}"
        )

    chat_id = int(
        getattr(
            chat,
            "id",
        )
    )

    return (
        f"https://splus.ir/c/"
        f"{chat_id}/"
        f"{message_id}"
    )



_SPLUS_PRIVATE_INVITE_PATTERN = re.compile(
    r"^/joingroup/([A-Za-z0-9_-]+?)/?$",
    re.IGNORECASE,
)

_SPLUS_PUBLIC_USERNAME_PATTERN = re.compile(
    r"^/([A-Za-z0-9_]+?)/?$",
    re.IGNORECASE,
)


def _parse_group_link(
    link: str,
) -> tuple[str, str | None]:
    """
    Returns:
        ("private", invite_hash)
        ("public", username)
        ("invalid", None)
    """

    link = (
        link or ""
    ).strip()

    if not link:
        return "invalid", None

    parsed = urlparse(
        link
    )

    if parsed.scheme.lower() != "https":
        return "invalid", None

    hostname = (
        parsed.hostname or ""
    ).lower()

    if hostname not in {
        "splus.ir",
        "www.splus.ir",
    }:
        return "invalid", None

    if parsed.query or parsed.fragment:
        return "invalid", None

    path = (
        parsed.path or ""
    ).strip()

    private_match = (
        _SPLUS_PRIVATE_INVITE_PATTERN.fullmatch(
            path
        )
    )

    if private_match is not None:
        return (
            "private",
            private_match.group(1),
        )

    public_match = (
        _SPLUS_PUBLIC_USERNAME_PATTERN.fullmatch(
            path
        )
    )

    if public_match is not None:
        username = (
            public_match.group(1)
        )

        if username.lower() == "joingroup":
            return "invalid", None

        return (
            "public",
            username,
        )

    return "invalid", None

@command(
    name="جوین گروه",
    permission="owner",
    chat_type="all",
    description="با لینک دعوت یا لینک عمومی وارد گروه سروش می‌شود.",
    native_name="join_group",
)
async def join_group(
    self: "GroupManagerPlugin",
    event: events.NewMessage.Event,
) -> None:

    # ---------------------------------------------------------
    # ARGUMENT
    # ---------------------------------------------------------

    if not event.args:

        await event.reply(
            "❌ لینک گروه را وارد کن.\n"
            "مثال:\n"
            + self.command_usage(
                event.command,
                "https://splus.ir/example",
                event=event,
            )
        )

        return

    group_link = (
        event.args[0]
        .strip()
    )

    link_type, target = _parse_group_link(
        group_link
    )

    if link_type == "invalid" or target is None:

        await event.reply(
            "❌ لینک گروه سروش معتبر نیست.\n"
            "فرمت‌های پشتیبانی‌شده:\n"
            "• https://splus.ir/<username>\n"
            "• https://splus.ir/joingroup/<hash>"
        )

        return

    # ---------------------------------------------------------
    # JOIN
    # ---------------------------------------------------------

    try:

        # -----------------------------------------------------
        # PUBLIC GROUP
        # -----------------------------------------------------

        if link_type == "public":

            entity = await self.client.get_entity(
                target
            )

            if not isinstance(
                entity,
                types.Channel,
            ):
                await event.reply(
                    "❌ این لینک به یک گروه/کانال عمومی قابل عضویت اشاره نمی‌کند."
                )
                return

            await self.client(
                functions.channels.JoinChannelRequest(
                    entity
                )
            )

        # -----------------------------------------------------
        # PRIVATE INVITE
        # -----------------------------------------------------

        else:

            await self.client(
                functions.messages.ImportChatInviteRequest(
                    target
                )
            )

    except Exception as exc:

        error_name = type(
            exc
        ).__name__

        error_text = str(
            exc
        )

        if (
            error_name
            == "UserAlreadyParticipantError"
        ):

            await event.reply(
                "ℹ️ این حساب از قبل عضو این گروه است."
            )

            return

        if (
            error_name
            == "InviteHashExpiredError"
        ):

            await event.reply(
                "❌ لینک دعوت منقضی شده است."
            )

            return

        if (
            error_name
            == "InviteHashInvalidError"
        ):

            await event.reply(
                "❌ لینک دعوت نامعتبر است."
            )

            return

        if (
            error_name
            in {
                "UsernameInvalidError",
                "UsernameNotOccupiedError",
            }
        ):

            await event.reply(
                "❌ گروه عمومی با این لینک پیدا نشد."
            )

            return

        if (
            error_name
            == "ChannelPrivateError"
        ):

            await event.reply(
                "❌ این گروه عمومی نیست یا دسترسی به آن امکان‌پذیر نیست."
            )

            return

        if (
            error_name
            == "InviteRequestSentError"
        ):

            await event.reply(
                "✅ درخواست عضویت ارسال شد "
                "و باید توسط ادمین گروه تأیید شود."
            )

            return

        if (
            error_name
            == "UsersTooMuchError"
        ):

            await event.reply(
                "❌ ظرفیت مجاز عضویت برای این حساب پر شده است."
            )

            return

        print(
            "❌ خطا در ورود به گروه:"
        )

        import traceback

        traceback.print_exc()

        await event.reply(
            "❌ ورود به گروه ناموفق بود.\n"
            f"نوع خطا: {error_name}"
            + (
                f"\nجزئیات: {error_text}"
                if error_text
                else ""
            )
        )

        return

    # ---------------------------------------------------------
    # SUCCESS
    # ---------------------------------------------------------

    if link_type == "public":

        await event.reply(
            "✅ با موفقیت وارد گروه عمومی شدم."
        )

    else:

        await event.reply(
            "✅ با موفقیت وارد گروه شدم."
        )



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


async def _get_message_statistics(
    client,
    chat,
) -> tuple[int | None, int | None, int | None]:

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
        return None, None, None

    existing_count = getattr(
        result,
        "count",
        None,
    )

    messages = getattr(
        result,
        "messages",
        None,
    ) or []

    if not messages:
        return existing_count, None, None

    latest_message_id = max(
        int(
            getattr(
                message,
                "id",
                0,
            )
        )
        for message in messages
    )

    sent_count = latest_message_id

    deleted_count = (
        max(
            0,
            sent_count
            - existing_count,
        )
        if existing_count is not None
        else None
    )

    return (
        existing_count,
        sent_count,
        deleted_count,
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
    native_name="group_stats",
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
        # MESSAGE STATISTICS
        # -------------------------------------------------

        (
            message_count,
            sent_message_count,
            deleted_message_count,
        ) = await _get_message_statistics(
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
                + format_project_jalali_date(
                    creation_date
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
                "💬 تعداد پیام‌های موجود در این لحظه: "
                f"{message_count:,}"
                if message_count is not None
                else
                "💬 تعداد پیام‌های موجود در این لحظه: نامشخص"
            ),
            (
                "📨 تعداد پیام‌های ارسال‌شده: "
                f"{sent_message_count:,}"
                if sent_message_count is not None
                else
                "📨 تعداد پیام‌های ارسال‌شده: نامشخص"
            ),
            (
                "🗑️ تعداد پیام‌های حذف‌شده: "
                f"{deleted_message_count:,}"
                if deleted_message_count is not None
                else
                "🗑️ تعداد پیام‌های حذف‌شده: نامشخص"
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