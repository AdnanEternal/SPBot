"""
عملیات واقعی میوت/بن روی کلاینت — تنها فایل این پلاگین که مستقیم با
API چت کار می‌کنه (بقیه‌ی پلاگین فقط دیتابیسه).

⚠️ فرض این فایل اینه که splusthon دقیقاً مثل Telethon متد
client.edit_permissions(chat, user, until_date=.., send_messages=False)
رو داره (کل این پروژه از اول همین فرض تلثون‌بودن splusthon رو داشته:
SoroushClient، StringSession، functions.messages.* و ...). اگه اسم یا
امضای این متد تو splusthon واقعی فرق داشت، فقط همین سه تابع پایین باید
عوض بشن؛ بقیه‌ی پلاگین (handlers.py، store.py) اصلاً کاری بهشون نداره.
"""

from datetime import timedelta

from core.time_manager import now_utc

from typing import Any, Optional


from splusthon import SoroushClient


async def resolve_target(client: SoroushClient, event: Any) -> Optional[int]:
    """
    کاربر هدف رو پیدا می‌کنه: اول از آرگومان (یوزرنیم/منشن تو
    event.args_text)، اگه نبود از ریپلای (پیامی که روش ریپلای شده).
    """
    target = event.args_text.strip() if event.args_text else ""
    if target:
        try:
            entity = await client.get_entity(target)
            return entity.id
        except Exception:
            return None

    reply = await event.get_reply_message()
    if reply is not None:
        return reply.sender_id

    return None


async def mute_user(
    client: SoroushClient,
    chat: Any,
    user_id: int,
    hours: Optional[int] = None,
) -> None:
    until_date = (
        now_utc() + timedelta(hours=hours)
        if hours
        else None
    )
    await client.edit_permissions(
        chat, 
        user_id,
        until_date=until_date, 
        send_messages=False,
        send_gifs=False,
        send_media=False,
        send_stickers=False,
        send_games=False,
        send_inline=False,
        send_polls=False
        )


async def unmute_user(client: SoroushClient, chat: Any, user_id: int) -> None:
    await client.edit_permissions(chat, user_id, send_messages=True)


async def ban_user(client: SoroushClient, chat: Any, user_id: int) -> None:
    await client.edit_permissions(chat, user_id, view_messages=False)