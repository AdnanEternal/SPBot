from splusthon.tl import functions, types
from config import config


async def is_chat_admin(
    client,
    chat,
    sender_id,
    *,
    raise_on_error: bool = False,
) -> bool:
    """
    بررسی می‌کند که sender_id در chat ادمین یا مالک است یا نه.
    برای چت خصوصی همیشه False برمی‌گرداند.

    اگر raise_on_error=True باشد، به‌جای False دادن در صورت خطا،
    خطا را دوباره raise می‌کند تا فراخوان بتواند «نمی‌دانم» را از
    «ادمین نیست» تشخیص بدهد.
    """
    try:
        if isinstance(chat, types.Chat):
            full_chat = await client(
                functions.messages.GetFullChatRequest(chat.id)
            )
            participants = full_chat.full_chat.participants.participants

            for p in participants:
                if p.user_id != sender_id:
                    continue
                if isinstance(
                    p,
                    (types.ChatParticipantCreator, types.ChatParticipantAdmin),
                ):
                    return True
            return False

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
            return any(
                getattr(p, "user_id", None) == sender_id
                for p in result.participants
            )

        else:
            return False

    except Exception as e:
        print(f"❌ خطا در بررسی دسترسی ادمین: {e}")
        if raise_on_error:
            raise
        return False


def is_owner(sender_id: int) -> bool:
    if sender_id is None:
        return False

    owner_id = config.get("BOT_OWNERS_ID", "")

    if not owner_id:
        return False

    owner_ids = {
        int(user_id.strip())
        for user_id in owner_id.split(",")
        if user_id.strip().isdigit()
    }

    return sender_id in owner_ids