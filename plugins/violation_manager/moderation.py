"""
عملیات واقعی میوت/بن روی کلاینت.
"""

from datetime import timedelta
from typing import Any, Optional

from core.time_manager import now_utc
from splusthon import SoroushClient


class ModerationError(Exception):
    pass


class TargetNotMemberError(
    ModerationError
):
    def __init__(self):
        super().__init__(
            "❌ کاربر در این گروه عضو نیست."
        )


class TargetIsAdminError(
    ModerationError
):
    def __init__(self):
        super().__init__(
            "❌ کاربر ادمین است و نمی‌توان او را مجازات کرد."
        )


class BotPermissionError(
    ModerationError
):
    def __init__(self):
        super().__init__(
            "❌ ربات ادمین نیست یا دسترسی لازم برای انجام این عملیات را ندارد."
        )


class ModerationOperationError(
    ModerationError
):
    pass


async def resolve_target(
    client: SoroushClient,
    event: Any,
) -> Optional[dict[str, Any]]:

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
                # Entity قابل resolve نیست.
                # خود moderation بعداً membership را بررسی می‌کند.
                return {
                    "id": user_id,
                    "entity": user_id,
                }

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

    try:
        return await client.get_entity(
            int(user_id)
        )

    except Exception:
        # اجازه می‌دهیم get_permissions خودش
        # membership/entity را بررسی کند.
        return int(user_id)


def _is_not_member_error(
    exc: Exception,
) -> bool:

    error_name = (
        exc.__class__.__name__
        .lower()
    )

    message = (
        str(exc)
        .lower()
    )

    return (
        "usernotparticipant" in error_name
        or "notparticipant" in error_name
        or "not participant" in message
        or "not a participant" in message
        or "not_member" in message
        or "not member" in message
        or (
            "404" in message
            and "not_found" in message
        )
    )


def _is_permission_error(
    exc: Exception,
) -> bool:

    error_name = (
        exc.__class__.__name__
        .lower()
    )

    message = (
        str(exc)
        .lower()
    )

    permission_phrases = (
        "chatadminrequired",
        "admin privileges are required",
        "chat admin privileges",
        "not enough rights",
        "right_forbidden",
        "ban users",
        "ban_user",
        "permission denied",
    )

    return (
        any(
            phrase in error_name
            for phrase in permission_phrases
        )
        or any(
            phrase in message
            for phrase in permission_phrases
        )
    )


async def _validate_moderation(
    client: SoroushClient,
    chat: Any,
    user: Any,
) -> None:

    # =========================================
    # BOT PERMISSIONS
    # =========================================

    try:
        me = await client.get_me()

        bot_permissions = (
            await client.get_permissions(
                chat,
                me,
            )
        )

    except Exception as exc:

        if _is_permission_error(exc):
            raise BotPermissionError()

        raise ModerationOperationError(
            f"❌ بررسی دسترسی ربات ناموفق بود:\n{exc}"
        ) from exc

    if (
        bot_permissions is None
        or not bot_permissions.is_admin
        or not bot_permissions.ban_users
    ):
        raise BotPermissionError()

    # =========================================
    # TARGET MEMBERSHIP
    # =========================================

    try:
        target_permissions = (
            await client.get_permissions(
                chat,
                user,
            )
        )

    except Exception as exc:

        if _is_not_member_error(exc):
            raise TargetNotMemberError()

        if _is_permission_error(exc):
            raise BotPermissionError()

        raise ModerationOperationError(
            f"❌ بررسی وضعیت کاربر ناموفق بود:\n{exc}"
        ) from exc

    if target_permissions is None:
        raise TargetNotMemberError()

    if getattr(
        target_permissions,
        "has_left",
        False,
    ):
        raise TargetNotMemberError()

    if getattr(
        target_permissions,
        "is_banned",
        False,
    ):
        raise TargetNotMemberError()

    # =========================================
    # TARGET ADMIN
    # =========================================

    if getattr(
        target_permissions,
        "is_admin",
        False,
    ):
        raise TargetIsAdminError()


async def mute_user(
    client: SoroushClient,
    chat: Any,
    user: Any,
    hours: Optional[int] = None,
    minutes: Optional[int] = None,
) -> None:

    await _validate_moderation(
        client,
        chat,
        user,
    )

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

    try:

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

    except Exception as exc:

        if _is_not_member_error(exc):
            raise TargetNotMemberError() from exc

        if _is_permission_error(exc):
            raise BotPermissionError() from exc

        message = str(exc).lower()

        if (
            "user_admin" in message
            or "user is an administrator" in message
            or "administrator" in message
        ):
            raise TargetIsAdminError() from exc

        raise ModerationOperationError(
            f"❌ اعمال میوت ناموفق بود:\n{exc}"
        ) from exc


async def unmute_user(
    client: SoroushClient,
    chat: Any,
    user: Any,
) -> None:

    await _validate_moderation(
        client,
        chat,
        user,
    )

    try:

        await client.edit_permissions(
            chat,
            user,
            send_messages=True,
        )

    except Exception as exc:

        if _is_not_member_error(exc):
            raise TargetNotMemberError() from exc

        if _is_permission_error(exc):
            raise BotPermissionError() from exc

        message = str(exc).lower()

        if (
            "user_admin" in message
            or "user is an administrator" in message
            or "administrator" in message
        ):
            raise TargetIsAdminError() from exc

        raise ModerationOperationError(
            f"❌ برداشتن میوت ناموفق بود:\n{exc}"
        ) from exc


async def ban_user(
    client: SoroushClient,
    chat: Any,
    user: Any,
) -> None:

    await _validate_moderation(
        client,
        chat,
        user,
    )

    try:

        await client.edit_permissions(
            chat,
            user,
            view_messages=False,
        )

    except Exception as exc:

        if _is_not_member_error(exc):
            raise TargetNotMemberError() from exc

        if _is_permission_error(exc):
            raise BotPermissionError() from exc

        message = str(exc).lower()

        if (
            "user_admin" in message
            or "user is an administrator" in message
            or "administrator" in message
        ):
            raise TargetIsAdminError() from exc

        raise ModerationOperationError(
            f"❌ بن کردن کاربر ناموفق بود:\n{exc}"
        ) from exc