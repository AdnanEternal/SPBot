"""
عملیات واقعی میوت/بن روی کلاینت.
"""

from datetime import timedelta
from typing import Any, Optional

from core.time_manager import now_utc
from splusthon import SoroushClient


class ModerationError(Exception):
    pass


class TargetNotMemberError(ModerationError):
    def __init__(self):
        super().__init__(
            "❌ کاربر در این گروه عضو نیست."
        )


class TargetIsAdminError(ModerationError):
    def __init__(self):
        super().__init__(
            "❌ کاربر ادمین است و نمی‌توان او را مجازات کرد."
        )


class BotPermissionError(ModerationError):
    def __init__(self):
        super().__init__(
            "❌ ربات ادمین نیست یا دسترسی لازم برای انجام این عملیات را ندارد."
        )


class ModerationOperationError(ModerationError):
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

    # =========================================
    # ARGUMENT
    # =========================================

    if target:

        # -------------------------------------
        # User ID
        # -------------------------------------

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
                return {
                    "id": user_id,
                    "entity": None,
                }

            return {
                "id": user_id,
                "entity": entity,
            }

        # -------------------------------------
        # Username / Mention
        # -------------------------------------

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

    # =========================================
    # REPLY
    # =========================================

    try:
        reply = await event.get_reply_message()
    except Exception:
        return None

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

    # اول از خود event استفاده کن.
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

    # بعد entity معمولی.
    try:
        return await client.get_entity(
            int(user_id)
        )
    except Exception:
        return None


def _is_not_member_error(
    exc: Exception,
) -> bool:

    error_name = (
        type(exc).__name__
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
        or "user_not_participant" in message
        or "not_member" in message
        or "not member" in message
    )


def _is_permission_error(
    exc: Exception,
) -> bool:

    error_name = (
        type(exc).__name__
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
        "rightforbidden",
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


def _is_admin_target_error(
    exc: Exception,
) -> bool:

    error_name = (
        type(exc).__name__
        .lower()
    )

    message = (
        str(exc)
        .lower()
    )

    admin_phrases = (
        "user_admin",
        "useradmin",
        "user is an administrator",
        "user is admin",
        "administrator",
    )

    return (
        any(
            phrase in error_name
            for phrase in admin_phrases
        )
        or any(
            phrase in message
            for phrase in admin_phrases
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
        # مهم:
        # باید InputPeer خود ربات را بگیریم،
        # نه User معمولی.
        me = await client.get_me(
            input_peer=True
        )

        if me is None:
            raise BotPermissionError()

        bot_permissions = (
            await client.get_permissions(
                chat,
                me,
            )
        )

    except BotPermissionError:
        raise

    except Exception as exc:

        if _is_permission_error(exc):
            raise BotPermissionError() from exc

        raise ModerationOperationError(
            f"❌ بررسی دسترسی ربات ناموفق بود:\n{exc}"
        ) from exc

    if (
        bot_permissions is None
        or not getattr(
            bot_permissions,
            "is_admin",
            False,
        )
        or not getattr(
            bot_permissions,
            "ban_users",
            False,
        )
    ):
        raise BotPermissionError()

    # =========================================
    # TARGET MEMBERSHIP
    # =========================================

    if user is None:
        raise ModerationOperationError(
            "❌ Entity کاربر پیدا نشد."
        )

    try:
        target_permissions = (
            await client.get_permissions(
                chat,
                user,
            )
        )

    except Exception as exc:

        if _is_not_member_error(exc):
            raise TargetNotMemberError() from exc

        if _is_permission_error(exc):
            raise BotPermissionError() from exc

        if _is_admin_target_error(exc):
            raise TargetIsAdminError() from exc

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
                hours=int(hours)
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

        if _is_admin_target_error(exc):
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
            until_date=None,
            send_messages=True,
            send_gifs=True,
            send_media=True,
            send_stickers=True,
            send_games=True,
            send_inline=True,
            send_polls=True,
        )

    except Exception as exc:

        if _is_not_member_error(exc):
            raise TargetNotMemberError() from exc

        if _is_permission_error(exc):
            raise BotPermissionError() from exc

        if _is_admin_target_error(exc):
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

        if _is_admin_target_error(exc):
            raise TargetIsAdminError() from exc

        raise ModerationOperationError(
            f"❌ بن کردن کاربر ناموفق بود:\n{exc}"
        ) from exc