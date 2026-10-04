"""
عملیات واقعی میوت/آنمیوت/بن.
"""

from datetime import timedelta
from typing import Any, Optional

from core.time_manager import now_utc
from splusthon import SoroushClient, errors


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
            "❌ ربات دسترسی لازم برای انجام این عملیات را ندارد."
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
                # اجازه می‌دهیم moderation بعداً
                # خودش input entity را resolve کند.
                return {
                    "id": user_id,
                    "entity": user_id,
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

    target_id = getattr(
        reply,
        "sender_id",
        None,
    )

    if target_id is None:
        return None

    return {
        "id": target_id,
        "entity": reply,
    }


async def resolve_user_entity(
    client: SoroushClient,
    event: Any,
    user_id: int,
) -> Optional[Any]:

    # اگر کاربر همان sender فعلی باشد.
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

    # ابتدا entity کامل.
    try:
        return await client.get_entity(
            int(user_id)
        )

    except Exception:
        pass

    # اگر از entity کامل نشد، خود ID را برگردان
    # تا moderation بتواند get_input_entity انجام دهد.
    return int(user_id)


def _is_not_member_error(
    exc: Exception,
) -> bool:

    if isinstance(
        exc,
        (
            errors.UserNotParticipantError,
            errors.UserKickedError,
        ),
    ):
        return True

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
        or "kicked" in message
    )


def _is_permission_error(
    exc: Exception,
) -> bool:

    if isinstance(
        exc,
        (
            errors.ChatAdminRequiredError,
            errors.RightForbiddenError,
        ),
    ):
        return True

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
        "administrator privileges",
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

    if isinstance(
        exc,
        errors.UserAdminInvalidError,
    ):
        return True

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


async def _resolve_moderation_input(
    client: SoroushClient,
    user: Any,
) -> Any:

    if user is None:
        raise TargetNotMemberError()

    # reply.Message
    get_input_sender = getattr(
        user,
        "get_input_sender",
        None,
    )

    if callable(get_input_sender):

        try:
            input_user = await get_input_sender()

        except Exception as exc:
            print(
                "❌ MODERATION INPUT DEBUG:",
                type(exc).__name__,
                repr(exc),
            )

            raise ModerationOperationError(
                "❌ دریافت اطلاعات کاربر برای انجام عملیات ناموفق بود:\n"
                f"{exc}"
            ) from exc

        if input_user is None:
            raise TargetNotMemberError()

        return input_user

    # Entity / ID / InputPeer
    try:
        input_user = await client.get_input_entity(
            user
        )

    except Exception as exc:
        print(
            "❌ MODERATION INPUT DEBUG:",
            type(exc).__name__,
            repr(exc),
        )

        raise ModerationOperationError(
            "❌ دریافت اطلاعات کاربر برای انجام عملیات ناموفق بود:\n"
            f"{exc}"
        ) from exc

    if input_user is None:
        raise TargetNotMemberError()

    return input_user


async def _validate_moderation(
    client: SoroushClient,
    chat: Any,
    user: Any,
) -> Any:
    """
    فقط target را به input entity تبدیل می‌کند.

    عمداً هیچ pre-check برای permission/member/admin
    انجام نمی‌شود.

    درخواست واقعی edit_permissions منبع حقیقت است؛
    چون pre-checkهای جداگانه می‌توانند بدون دلیل
    جلوی عملیات واقعی را بگیرند.
    """

    return await _resolve_moderation_input(
        client,
        user,
    )


async def mute_user(
    client: SoroushClient,
    chat: Any,
    user: Any,
    hours: Optional[int] = None,
    minutes: Optional[int] = None,
    seconds: Optional[int] = None,
) -> None:

    user = await _validate_moderation(
        client,
        chat,
        user,
    )

    # =========================================
    # MUTE DURATION
    # =========================================

    if seconds is not None:

        until_date = (
            now_utc()
            + timedelta(
                seconds=max(
                    1,
                    int(seconds),
                )
            )
        )

    elif minutes is not None:

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

    # =========================================
    # REAL MODERATION REQUEST
    # =========================================

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

        print(
            "❌ MUTE DEBUG:",
            type(exc).__name__,
            repr(exc),
        )

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

    user = await _validate_moderation(
        client,
        chat,
        user,
    )

    # =========================================
    # REAL MODERATION REQUEST
    # =========================================

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

        print(
            "❌ UNMUTE DEBUG:",
            type(exc).__name__,
            repr(exc),
        )

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

    user = await _validate_moderation(
        client,
        chat,
        user,
    )

    # =========================================
    # REAL MODERATION REQUEST
    # =========================================

    try:

        await client.edit_permissions(
            chat,
            user,
            view_messages=False,
        )

    except Exception as exc:

        print(
            "❌ BAN DEBUG:",
            type(exc).__name__,
            repr(exc),
        )

        if _is_not_member_error(exc):
            raise TargetNotMemberError() from exc

        if _is_permission_error(exc):
            raise BotPermissionError() from exc

        if _is_admin_target_error(exc):
            raise TargetIsAdminError() from exc

        raise ModerationOperationError(
            f"❌ بن کردن کاربر ناموفق بود:\n{exc}"
        ) from exc