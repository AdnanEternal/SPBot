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

async def resolve_target(
    client: SoroushClient,
    event: Any,
) -> Optional[dict[str, Any]]:
    """
    کاربر هدف را پیدا می‌کند و هم ID و هم Entity را برمی‌گرداند.

    خروجی:
        {
            "id": int,
            "entity": object,
        }
    """

    target = (
        event.args_text.strip()
        if event.args_text
        else ""
    )

    if target:

        # -----------------------------------------
        # User ID
        # -----------------------------------------

        if target.lstrip("-").isdigit():

            try:
                user_id = int(target)
            except ValueError:
                return None

            try:
                entity = await client.get_entity(
                    user_id
                )

            except Exception:
                return None

            return {
                "id": user_id,
                "entity": entity,
            }

        # -----------------------------------------
        # Username / Mention
        # -----------------------------------------

        try:
            entity = await client.get_entity(
                target
            )

        except Exception:
            return None

        return {
            "id": entity.id,
            "entity": entity,
        }

    # -----------------------------------------
    # Reply
    # -----------------------------------------

    reply = await event.get_reply_message()

    if reply is None:
        return None

    try:
        entity = await reply.get_sender()
    except Exception:
        entity = None

    if entity is None:
        return None

    return {
        "id": entity.id,
        "entity": entity,
    }


async def resolve_user_entity(
    client: SoroushClient,
    event: Any,
    user_id: int,
) -> Optional[Any]:
    """
    Entity کاربر را برای عملیات moderation پیدا می‌کند.

    اولویت:
    1. sender خود event اگر همان user باشد.
    2. get_entity با ID.
    """

    # -----------------------------------------
    # Event sender
    # -----------------------------------------

    try:
        sender = await event.get_sender()

        if (
            sender is not None
            and getattr(sender, "id", None)
            == int(user_id)
        ):
            return sender

    except Exception:
        pass

    # -----------------------------------------
    # Direct entity lookup
    # -----------------------------------------

    try:
        return await client.get_entity(
            int(user_id)
        )

    except Exception:
        return None


async def mute_user(
    client: SoroushClient,
    chat: Any,
    user: Any,
    hours: Optional[int] = None,
    minutes: Optional[int] = None,
) -> None:

    if minutes is not None:
        until_date = (
            now_utc()
            + timedelta(
                minutes=max(
                    1,
                    int(minutes),
                )
            )
        )

    elif hours:
        until_date = (
            now_utc()
            + timedelta(
                hours=hours
            )
        )

    else:
        until_date = None

    await client.edit_permissions(
        chat,
        user,
        until_date=until_date,
        send_messages=False,
        send_gifs=False,
        send_media=False,
        send_stickers=False,
        send_games=False,
        send_inline=False,
        send_polls=False,
    )


async def unmute_user(
    client: SoroushClient,
    chat: Any,
    user: Any,
) -> None:

    await client.edit_permissions(
        chat,
        user,
        send_messages=True,
    )


async def ban_user(
    client: SoroushClient,
    chat: Any,
    user: Any,
) -> None:

    await client.edit_permissions(
        chat,
        user,
        view_messages=False,
    )