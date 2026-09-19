from splusthon.tl import functions, types
from config import config
import asyncio
import traceback
async def is_chat_admin(
    client,
    chat,
    sender_id,
    *,
    raise_on_error: bool = False,
) -> bool:

    async def check() -> bool:

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

            for p in participants:

                if p.user_id != sender_id:
                    continue

                if isinstance(
                    p,
                    (
                        types.ChatParticipantCreator,
                        types.ChatParticipantAdmin,
                    ),
                ):
                    return True

            return False

        if isinstance(chat, types.Channel):

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
                getattr(p, "user_id", None)
                == sender_id
                for p in result.participants
            )

        return False

    try:
        return await asyncio.wait_for(
            check(),
            timeout=15,
        )

    except asyncio.TimeoutError as exc:
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