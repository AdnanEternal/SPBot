from typing import TYPE_CHECKING

from splusthon import events

import re

from core.decorators import command, on_bus_event, on_event
from core.permissions import is_chat_admin, is_owner

from . import moderation
from core.ttl_cache import TTLCache
# فقط برای type checker ایمپورت می‌شه، موقع اجرا نه؛ اینجوری import
# چرخه‌ای (handlers.py <-> plugin.py) پیش نمیاد.
if TYPE_CHECKING:
    from .plugin import ViolationManagerPlugin

# اگه مدت میوتِ گروه هنوز تنظیم نشده باشه (نه با !مجازات میوت، نه با
# مجازات خودکار)، از این مقدار برای !میوت دستی استفاده می‌شه.




DEFAULT_MUTE_HOURS = 1


SOFT_SCORE_MAX = 5


MUTE_DURATION_UNITS = {
    "ث": 1,
    "ثانیه": 1,
    "س": 60 * 60,
    "ساعت": 60 * 60,
    "ر": 24 * 60 * 60,
    "روز": 24 * 60 * 60,
}

REPLY_TRIGGERS = {
    "ban": {
        "بن",
        "ریم",
    },
    "mute": {
        "میوت",
        "سکوت",
    },
    "unmute": {
        "آنمیوت",
        "انمیوت",
        "ان میوت",
        "آن میوت",
        "حذف میوت"
    },
}


def _find_reply_trigger(
    text: str,
    trigger_type: str,
) -> str | None:
    normalized = (
        text or ""
    ).strip()

    triggers = REPLY_TRIGGERS.get(
        trigger_type,
        (),
    )

    # تریگرهای طولانی‌تر اول بررسی شوند.
    for trigger in sorted(
        triggers,
        key=len,
        reverse=True,
    ):
        if normalized == trigger:
            return trigger

    return None

def _extract_reply_mute_trigger(
    text: str,
) -> tuple[str | None, str]:
    normalized = (
        text or ""
    ).strip()

    for trigger in sorted(
        REPLY_TRIGGERS["mute"],
        key=len,
        reverse=True,
    ):
        pattern = re.fullmatch(
            rf"{re.escape(trigger)}\s*(.*)",
            normalized,
        )

        if pattern:
            return (
                trigger,
                pattern.group(1).strip(),
            )

    return None, ""

def _parse_reply_mute_duration(
    text: str,
) -> tuple[bool, int | None]:
    """
    فرمت‌های مجاز:

    میوت
    میوت 2
    میوت 2 ساعت
    میوت2ساعت
    میوت 200 ث
    میوت200ثانیه
    میوت 6 روز
    میوت6روز

    همین فرمت‌ها برای تمام تریگرهای موجود
    در REPLY_TRIGGERS["mute"] معتبر هستند.

    عدد بدون واحد = ساعت
    بدون عدد = میوت دائمی

    خروجی:
        (valid, seconds)
        seconds=None یعنی دائمی
    """

    trigger, duration_text = (
        _extract_reply_mute_trigger(text)
    )

    if trigger is None:
        return False, None

    # فقط خود تریگر = میوت دائمی
    if not duration_text:
        return True, None

    normalized = duration_text

    # حذف کاراکترهای نامرئی
    normalized = re.sub(
        r"[\u200c\u200d\u200e\u200f\ufeff]",
        "",
        normalized,
    )

    # تبدیل ارقام فارسی و عربی به انگلیسی
    normalized = normalized.translate(
        str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
            "01234567890123456789",
        )
    )

    normalized = normalized.strip()

    # عدد تنها = ساعت
    match = re.fullmatch(
        r"(\d+)",
        normalized,
    )

    if match:
        value = int(match.group(1))

        if value <= 0:
            return False, None

        return (
            True,
            value * 60 * 60,
        )

    # عدد + واحد
    match = re.fullmatch(
        r"(\d+)\s*(ثانیه|ث|ساعت|س|روز|ر)",
        normalized,
    )

    if not match:
        return False, None

    value = int(
        match.group(1)
    )

    unit = match.group(2)

    if value <= 0:
        return False, None

    return (
        True,
        value * MUTE_DURATION_UNITS[unit],
    )

async def _resolve_group_entity(
    self: "ViolationManagerPlugin",
    group_id: int,
):
    try:
        dialogs = await self.client.get_dialogs()

    except Exception as e:
        print(
            "⚠️ دریافت لیست گروه‌ها برای اجرای ریموت ناموفق بود: "
            f"{e}"
        )
        return None

    for dialog in dialogs:
        if dialog.id == group_id:
            return dialog.entity

    return None


def _is_remote_group_id(value: str) -> bool:
    if not value:
        return False

    try:
        return int(value) < 0
    except (TypeError, ValueError):
        return False


def _extract_optional_group_target(
    raw: str,
) -> tuple[int | None, str, bool]:
    raw = (raw or "").strip()

    if not raw:
        return None, "", False

    parts = raw.split()
    candidate = parts[-1]

    if not _is_remote_group_id(candidate):
        return None, raw, False

    try:
        target_group = int(candidate)
    except (TypeError, ValueError):
        return None, raw, False

    return (
        target_group,
        " ".join(parts[:-1]).strip(),
        True,
    )


async def _resolve_group_target(
    self: "ViolationManagerPlugin",
    event,
) -> tuple[int | None, str, bool]:

    target_group, remaining, remote = (
        _extract_optional_group_target(
            event.args_text or ""
        )
    )

    # -----------------------------
    # REMOTE
    # -----------------------------

    if remote:
        if not is_owner(event.sender_id):
            await event.reply(
                "❌ اجرای ریموت این کامند فقط برای Owner مجازه."
            )
            return None, remaining, True

        return target_group, remaining, True

    # -----------------------------
    # LOCAL
    # -----------------------------

    if not event.is_group:
        return None, remaining, False

    try:
        allowed = await is_chat_admin(
            self.client,
            await event.get_chat(),
            event.sender_id,
            raise_on_error=True,
        )

    except Exception as e:
        print(
            "⚠️ بررسی دسترسی ادمین برای "
            f"Violation Manager ناموفق بود: {e}"
        )

        await event.reply(
            "❌ نتونستم دسترسی ادمین شما رو بررسی کنم."
        )
        return None, remaining, False

    if not allowed:
        await event.reply(
            "❌ این کامند فقط برای ادمین‌های گروه مجازه."
        )
        return None, remaining, False

    return event.chat_id, remaining, False

def _normalize_violation_score(
    value,
) -> int:
    try:
        value = int(value)
    except (
        TypeError,
        ValueError,
    ):
        return 0

    return max(
        0,
        min(
            10,
            value,
        ),
    )


def _mute_minutes_for_score(
    score: int,
) -> int:
    """
    امتیاز تخلف -> مدت میوت خودکار

    1  = 5 دقیقه
    2  = 10 دقیقه
    3  = 15 دقیقه
    4  = 20 دقیقه
    5  = 30 دقیقه
    6  = 1 ساعت
    7  = 2 ساعت
    8  = 4 ساعت
    9  = 6 ساعت
    10 = 12 ساعت
    """
    durations = {
        1: 5,
        2: 10,
        3: 15,
        4: 20,
        5: 30,
        6: 60,
        7: 120,
        8: 240,
        9: 360,
        10: 720,
    }

    return durations.get(
        score,
        5,
    )


class PunishmentThrottle:
    TTL_SECONDS = 30
    MAX_ENTRIES = 5000

    def __init__(self) -> None:
        self._cache = TTLCache[
            tuple[int, int],
            int,
        ](
            max_entries=self.MAX_ENTRIES,
            ttl_seconds=self.TTL_SECONDS,
        )

    def should_punish(
        self,
        group_id: int,
        user_id: int,
        score: int,
    ) -> bool:
        key = (
            group_id,
            user_id,
        )

        # هر نوع مجازات موفق، برای این incident تا
        # پایان TTL جلوی مجازات دوباره را می‌گیرد.
        return (
            self._cache.get(key)
            is None
        )

    def mark_punished(
        self,
        group_id: int,
        user_id: int,
        score: int,
    ) -> None:
        self._cache.set(
            (
                group_id,
                user_id,
            ),
            int(score),
        )

punishment_throttle = PunishmentThrottle()

async def _display_name(event, user_id: int) -> str:
    try:
        sender = await event.get_sender()

        if sender is not None:
            return (
                getattr(sender, "username", None)
                or getattr(sender, "first_name", None)
                or str(user_id)
            )
    except Exception:
        pass

    return str(user_id)


async def _notify(event, text: str):
    try:
        return await event.reply(text)

    except Exception:
        try:
            return await event.respond(text)

        except Exception as e:
            print(
                f"⚠️ نتونستم پیام تخلف رو ارسال کنم: {e}"
            )
            return None


async def _safe_reply(
    event,
    text: str,
) -> None:

    try:
        await event.reply(text)
        return

    except Exception:
        pass

    try:
        await event.respond(text)
        return

    except Exception as exc:
        print(
            "⚠️ ارسال پیام Violation Manager ناموفق بود: "
            f"type={type(exc).__name__} "
            f"error={exc}"
        )


@command(
    name="حذف سابقه",
    permission="admin",
    chat_type="group",
    description="سابقه تخلفات یک کاربر را پاک می‌کند.",
)
async def clear_record(
    self: "ViolationManagerPlugin",
    event: events.NewMessage.Event,
) -> None:
    # اولویت با ریپلای است.
    reply = await event.get_reply_message()

    if reply is not None:
        target_id = reply.sender_id

    else:
        # اگر ریپلای نبود، یوزرنیم را از پارامتر می‌گیریم.
        username = (event.args_text or "").strip()

        if not username:
            await event.reply(
                "مثال:\n"
                "روی پیام کاربر ریپلای کن و !حذف سابقه بزن.\n"
                "یا:\n"
                "!حذف سابقه @username"
            )
            return

        try:
            entity = await self.client.get_entity(username)
            target_id = entity.id
        except Exception:
            await event.reply(
                f"❌ نتونستم کاربر `{username}` رو پیدا کنم."
            )
            return

    count = await self.violations.get_count(
        event.chat_id,
        target_id,
    )

    if count == 0:
        await event.reply(
            f"ℹ️ برای کاربر `{target_id}` هیچ سابقه‌ای ثبت نشده."
        )
        return

    await self.violations.reset(
        event.chat_id,
        target_id,
    )

    await event.reply(
        f"✅ سابقه‌ی {count} تخلف کاربر `{target_id}` پاک شد."
    )




@command(
    name="لیست متخلفان",
    permission="admin",
    chat_type="group",
    description="لیست کاربران متخلف این گروه رو نشون می‌ده.",
)
async def list_violators(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    users = await self.violations.get_users(event.chat_id)

    if not users:
        await event.reply("✅ هیچ کاربر متخلفی در این گروه ثبت نشده.")
        return

    lines = [
        f"👤 `{row['user_id']}` — ⚠️ {row['violation_count']} تخلف"
        for row in users
    ]

    await event.reply("⚠️ کاربران متخلف این گروه:\n\n" + "\n".join(lines))


@command(
    name="سقف تخلف",
    permission="admin",
    chat_type="group",
    description="حداکثر تعداد تخلف مجاز قبل از مجازات خودکار رو تنظیم می‌کنه.",
)
async def set_max_violations(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    value = event.args_text.strip()
    if not value.isdigit() or int(value) <= 0:
        await event.reply("مثال: !سقف تخلف 3")
        return

    await self.settings.set_max_violations(event.chat_id, int(value))
    await event.reply(f"سقف تخلف این گروه با موفقیت به {value} تنظیم شد!")


@command(
    name="مجازات میوت",
    permission="admin",
    chat_type="group",
    description="مجازات خودکار را روی میوت تنظیم می‌کند؛ بدون ساعت یعنی دائمی.",
)
async def set_punishment_mute(
    self,
    event: events.NewMessage.Event,
) -> None:
    value = (event.args_text or "").strip()

    # بدون آرگومان = میوت دائمی
    if not value:
        await self.settings.set_punishment_mute(
            event.chat_id,
            None,
        )

        await event.reply(
            "✅ مجازات خودکار روی «میوت دائمی» تنظیم شد."
        )
        return

    # با ساعت
    if not value.isdigit():
        await event.reply(
            "مثال:\n"
            "!مجازات میوت\n"
            "یا:\n"
            "!مجازات میوت 6"
        )
        return

    hours = int(value)

    if hours <= 0:
        await event.reply(
            "❌ تعداد ساعت باید بیشتر از صفر باشد."
        )
        return

    await self.settings.set_punishment_mute(
        event.chat_id,
        hours,
    )

    await event.reply(
        f"✅ مجازات خودکار روی "
        f"«میوت {hours} ساعته» تنظیم شد."
    )
@command(
    name="مجازات بن",
    permission="admin",
    chat_type="group",
    description="مجازات خودکارِ این گروه رو بن می‌ذاره.",
)
async def set_punishment_ban(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    await self.settings.set_punishment_ban(event.chat_id)
    await event.reply("نوع مجازات این گروه با موفقیت به بن تغییر کرد!")


@command(
    name="سابقه ی من",
    permission="everyone",
    chat_type="group",
    description="تعداد تخلف‌های خودت تو این گروه رو نشون می‌ده.",
)
async def my_record(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    count = await self.violations.get_count(event.chat_id, event.sender_id)
    await event.reply(f"شما تا الان {count} بار تو این گروه تخلف کردید.")


@command(
    name="میوت",
    permission="everyone",
    chat_type="all",
    description="یه کاربر رو میوت می‌کنه؛ محلی برای ادمین و ریموت برای Owner.",
)
async def mute_command(
    self: "ViolationManagerPlugin",
    event: events.NewMessage.Event,
) -> None:

    target_group, target_arg, remote = (
        await _resolve_group_target(
            self,
            event,
        )
    )

    if target_group is None:
        await _safe_reply(
            event,
            "مثال:\n"
            "داخل گروه:\n"
            "!میوت @username\n"
            "یا روی پیام کاربر ریپلای کن.\n\n"
            "ریموت توسط Owner:\n"
            "!میوت @username -100123456",
        )
        return

    target_id = None
    target_entity = None

    # =========================================
    # REMOTE
    # =========================================

    if remote:

        if not target_arg:
            await _safe_reply(
                event,
                "❌ برای اجرای ریموت باید کاربر را مشخص کنی.\n"
                "مثال:\n"
                "!میوت 49245702 -100123456\n"
                "یا:\n"
                "!میوت @username -100123456",
            )
            return

        if target_arg.lstrip("-").isdigit():

            try:
                target_id = int(target_arg)
            except ValueError:
                await _safe_reply(
                    event,
                    "❌ شناسه کاربر نامعتبر است.",
                )
                return

            target_entity = (
                await moderation.resolve_user_entity(
                    self.client,
                    event,
                    target_id,
                )
            )

        else:

            try:
                target_entity = (
                    await self.client.get_entity(
                        target_arg
                    )
                )

                target_id = target_entity.id

            except Exception:
                await _safe_reply(
                    event,
                    f"❌ نتونستم کاربر `{target_arg}` رو پیدا کنم.",
                )
                return

    # =========================================
    # LOCAL
    # =========================================

    else:

        target = await moderation.resolve_target(
            self.client,
            event,
        )

        if target is None:
            await _safe_reply(
                event,
                "مثال: !میوت @username\n"
                "یا روی پیام شخص ریپلای کن.",
            )
            return

        target_id = target["id"]
        target_entity = target["entity"]

        if target_entity is None:
            target_entity = (
                await moderation.resolve_user_entity(
                    self.client,
                    event,
                    target_id,
                )
            )

    # =========================================
    # ENTITY
    # =========================================

    if target_entity is None:
        await _safe_reply(
            event,
            f"❌ نتونستم اطلاعات کاربر `{target_id}` رو پیدا کنم.",
        )
        return

    # =========================================
    # GROUP
    # =========================================

    settings = await self.settings.get(
        target_group
    )

    hours = (
        settings["mute_hours"]
        or DEFAULT_MUTE_HOURS
    )

    chat = await _resolve_group_entity(
        self,
        target_group,
    )

    if chat is None:
        await _safe_reply(
            event,
            f"❌ گروه `{target_group}` پیدا نشد.\n"
            "مطمئن شو ربات داخل این گروه حضور داره.",
        )
        return

    # =========================================
    # MODERATION
    # =========================================

    try:

        await moderation.mute_user(
            self.client,
            chat,
            target_entity,
            hours=hours,
        )

    except moderation.ModerationError as exc:

        await _safe_reply(
            event,
            str(exc),
        )
        return

    except Exception as exc:

        print(
            "❌ خطای غیرمنتظره در !میوت:",
            exc,
        )

        await _safe_reply(
            event,
            f"❌ خطای غیرمنتظره در میوت:\n{exc}",
        )
        return

    await _safe_reply(
        event,
        f"✅ کاربر `{target_id}` "
        f"به مدت {hours} ساعت میوت شد.\n"
        f"📍 گروه: `{target_group}`",
    )


@command(
    name="آنمیوت",
    permission="everyone",
    chat_type="all",
    description="میوت یه کاربر رو برمی‌داره؛ محلی برای ادمین و ریموت برای Owner.",
)
async def unmute_command(
    self: "ViolationManagerPlugin",
    event: events.NewMessage.Event,
) -> None:

    target_group, target_arg, remote = (
        await _resolve_group_target(
            self,
            event,
        )
    )

    if target_group is None:
        await _safe_reply(
            event,
            "مثال:\n"
            "داخل گروه:\n"
            "!آنمیوت @username\n"
            "یا روی پیام کاربر ریپلای کن.\n\n"
            "ریموت توسط Owner:\n"
            "!آنمیوت @username -100123456",
        )
        return

    target_id = None
    target_entity = None

    # =========================================
    # REMOTE
    # =========================================

    if remote:

        if not target_arg:
            await _safe_reply(
                event,
                "❌ برای اجرای ریموت باید کاربر را مشخص کنی.",
            )
            return

        if target_arg.lstrip("-").isdigit():

            try:
                target_id = int(target_arg)
            except ValueError:
                await _safe_reply(
                    event,
                    "❌ شناسه کاربر نامعتبر است.",
                )
                return

            target_entity = (
                await moderation.resolve_user_entity(
                    self.client,
                    event,
                    target_id,
                )
            )

        else:

            try:
                target_entity = (
                    await self.client.get_entity(
                        target_arg
                    )
                )

                target_id = target_entity.id

            except Exception:
                await _safe_reply(
                    event,
                    f"❌ نتونستم کاربر `{target_arg}` رو پیدا کنم.",
                )
                return

    # =========================================
    # LOCAL
    # =========================================

    else:

        target = await moderation.resolve_target(
            self.client,
            event,
        )

        if target is None:
            await _safe_reply(
                event,
                "مثال: !آنمیوت @username\n"
                "یا روی پیام شخص ریپلای کن.",
            )
            return

        target_id = target["id"]
        target_entity = target["entity"]

        if target_entity is None:
            target_entity = (
                await moderation.resolve_user_entity(
                    self.client,
                    event,
                    target_id,
                )
            )

    if target_entity is None:
        await _safe_reply(
            event,
            f"❌ نتونستم اطلاعات کاربر `{target_id}` رو پیدا کنم.",
        )
        return

    chat = await _resolve_group_entity(
        self,
        target_group,
    )

    if chat is None:
        await _safe_reply(
            event,
            f"❌ گروه `{target_group}` پیدا نشد.\n"
            "مطمئن شو ربات داخل این گروه حضور داره.",
        )
        return

    try:

        await moderation.unmute_user(
            self.client,
            chat,
            target_entity,
        )

    except moderation.ModerationError as exc:

        await _safe_reply(
            event,
            str(exc),
        )
        return

    except Exception as exc:

        print(
            "❌ خطای غیرمنتظره در !آنمیوت:",
            exc,
        )

        await _safe_reply(
            event,
            f"❌ خطای غیرمنتظره در برداشتن میوت:\n{exc}",
        )
        return

    await _safe_reply(
        event,
        f"✅ میوتِ کاربر `{target_id}` برداشته شد.\n"
        f"📍 گروه: `{target_group}`",
    )


@command(
    name="بن",
    permission="everyone",
    chat_type="all",
    description="یه کاربر رو بن می‌کنه؛ محلی برای ادمین و ریموت برای Owner.",
)
async def ban_command(
    self: "ViolationManagerPlugin",
    event: events.NewMessage.Event,
) -> None:

    target_group, target_arg, remote = (
        await _resolve_group_target(
            self,
            event,
        )
    )

    if target_group is None:
        await _safe_reply(
            event,
            "مثال:\n"
            "داخل گروه:\n"
            "!بن @username\n"
            "یا روی پیام کاربر ریپلای کن.\n\n"
            "ریموت توسط Owner:\n"
            "!بن @username -100123456",
        )
        return

    target_id = None
    target_entity = None

    # =========================================
    # REMOTE
    # =========================================

    if remote:

        if not target_arg:
            await _safe_reply(
                event,
                "❌ برای اجرای ریموت باید کاربر را مشخص کنی.\n"
                "مثال:\n"
                "!بن 49245702 -100123456\n"
                "یا:\n"
                "!بن @username -100123456",
            )
            return

        if target_arg.lstrip("-").isdigit():

            try:
                target_id = int(target_arg)
            except ValueError:
                await _safe_reply(
                    event,
                    "❌ شناسه کاربر نامعتبر است.",
                )
                return

            target_entity = (
                await moderation.resolve_user_entity(
                    self.client,
                    event,
                    target_id,
                )
            )

        else:

            try:
                target_entity = (
                    await self.client.get_entity(
                        target_arg
                    )
                )

                target_id = target_entity.id

            except Exception:
                await _safe_reply(
                    event,
                    f"❌ نتونستم کاربر `{target_arg}` رو پیدا کنم.",
                )
                return

    # =========================================
    # LOCAL
    # =========================================

    else:

        target = await moderation.resolve_target(
            self.client,
            event,
        )

        if target is None:
            await _safe_reply(
                event,
                "مثال: !بن @username\n"
                "یا روی پیام شخص ریپلای کن.",
            )
            return

        target_id = target["id"]
        target_entity = target["entity"]

        if target_entity is None:
            target_entity = (
                await moderation.resolve_user_entity(
                    self.client,
                    event,
                    target_id,
                )
            )

    # =========================================
    # ENTITY
    # =========================================

    if target_entity is None:
        await _safe_reply(
            event,
            f"❌ نتونستم اطلاعات کاربر `{target_id}` رو پیدا کنم.",
        )
        return

    # =========================================
    # GROUP
    # =========================================

    chat = await _resolve_group_entity(
        self,
        target_group,
    )

    if chat is None:
        await _safe_reply(
            event,
            f"❌ گروه `{target_group}` پیدا نشد.\n"
            "مطمئن شو ربات داخل این گروه حضور داره.",
        )
        return

    # =========================================
    # MODERATION
    # =========================================

    try:

        await moderation.ban_user(
            self.client,
            chat,
            target_entity,
        )

    except moderation.ModerationError as exc:

        await _safe_reply(
            event,
            str(exc),
        )
        return

    except Exception as exc:

        print(
            "❌ خطای غیرمنتظره در !بن:",
            exc,
        )

        await _safe_reply(
            event,
            f"❌ خطای غیرمنتظره در بن:\n{exc}",
        )
        return

    await _safe_reply(
        event,
        f"✅ کاربر `{target_id}` بن شد.\n"
        f"📍 گروه: `{target_group}`",
    )

@on_event(events.NewMessage(incoming=True))
async def on_reply_shortcut(
    self: "ViolationManagerPlugin",
    event: events.NewMessage.Event,
) -> None:

    if not event.is_group or not event.is_reply:
        return

    text = (
        event.raw_text or ""
    ).strip()

    mute_trigger, mute_args = (
        _extract_reply_mute_trigger(text)
    )

    ban_trigger = _find_reply_trigger(
        text,
        "ban",
    )

    unmute_trigger = _find_reply_trigger(
        text,
        "unmute",
    )

    # این پیام هیچ Reply Trigger معتبری نیست.
    if (
        mute_trigger is None
        and ban_trigger is None
        and unmute_trigger is None
    ):
        return

    mute_seconds = None

    if mute_trigger is not None:

        valid_mute, mute_seconds = (
            _parse_reply_mute_duration(text)
        )

        if not valid_mute:
            await _safe_reply(
                event,
                "❌ فرمت میوت نامعتبر است.\n"
                "مثال:\n"
                "میوت\n"
                "میوت 2\n"
                "میوت 200 ث\n"
                "میوت 2 ساعت\n"
                "میوت 6 روز\n"
                "سکوت 2 ساعت",
            )
            return

    try:
        chat = await event.get_chat()

        allowed = await is_chat_admin(
            self.client,
            chat,
            event.sender_id,
            raise_on_error=True,
        )

    except Exception as exc:
        print(
            "⚠️ بررسی دسترسی shortcut ناموفق بود:",
            exc,
        )
        return

    if not allowed:
        return

    try:
        reply = await event.get_reply_message()
    except Exception:
        return

    if reply is None:
        return

    target_id = getattr(
        reply,
        "sender_id",
        None,
    )

    if target_id is None:
        return

    
    # =========================================
    # MUTE
    # =========================================

    if mute_trigger is not None:

        try:
            await moderation.mute_user(
                self.client,
                chat,
                reply,
                seconds=mute_seconds,
            )

        except moderation.ModerationError as exc:

            await _safe_reply(
                event,
                str(exc),
            )
            return

        except Exception as exc:

            print(
                "❌ خطای shortcut میوت:",
                exc,
            )

            await _safe_reply(
                event,
                f"❌ خطای غیرمنتظره در میوت:\n{exc}",
            )
            return

        if mute_seconds is None:

            response = (
                f"کاربر `{target_id}` "
                "به‌صورت دائمی میوت شد."
            )

        else:

            if mute_seconds % (
                24 * 60 * 60
            ) == 0:

                duration_text = (
                    f"{mute_seconds // (24 * 60 * 60)} روز"
                )

            elif mute_seconds % (
                60 * 60
            ) == 0:

                duration_text = (
                    f"{mute_seconds // (60 * 60)} ساعت"
                )

            else:

                duration_text = (
                    f"{mute_seconds} ثانیه"
                )

            response = (
                f"کاربر `{target_id}` "
                f"به مدت {duration_text} میوت شد."
            )

        await _safe_reply(
            event,
            response,
        )
        return

    # =========================================
    # UNMUTE
    # =========================================

    if unmute_trigger is not None:

        try:
            await moderation.unmute_user(
                self.client,
                chat,
                reply,
            )
 
        except moderation.ModerationError as exc:

            await _safe_reply(
                event,
                str(exc),
            )
            return

        except Exception as exc:

            print(
                "❌ خطای shortcut آنمیوت:",
                exc,
            )

            await _safe_reply(
                event,
                f"❌ خطای غیرمنتظره در برداشتن میوت:\n{exc}",
            )
            return

        await _safe_reply(
            event,
            f"میوتِ کاربر `{target_id}` برداشته شد.",
        )
        return
    # =========================================
    # BAN
    # =========================================

    if ban_trigger is not None:

        try:

            await moderation.ban_user(
                self.client,
                chat,
                reply,
            )

        except moderation.ModerationError as exc:

            await _safe_reply(
                event,
                str(exc),
            )
            return

        except Exception as exc:

            print(
                "❌ خطای shortcut بن:",
                exc,
            )

            await _safe_reply(
                event,
                f"❌ خطای غیرمنتظره در بن:\n{exc}",
            )
            return

        await _safe_reply(
            event,
            f"کاربر `{target_id}` بن شد.",
        )

@on_bus_event("punishment_request")
async def on_punishment_request(
    self: "ViolationManagerPlugin",
    event,
    group_id: int,
    user_id: int,
    reason: str,
    source: str = "unknown",
) -> None:
    """
    درخواست مجازات از پلاگین‌های مستقل.

    این مسیر فقط مجازات را انجام می‌دهد
    و هیچ سابقه‌ای در Violation Manager ثبت نمی‌کند.
    """
    target_entity = (
        await moderation.resolve_user_entity(
            self.client,
            event,
            user_id,
        )
    )

    if target_entity is None:
        print(
            "⚠️ Entity کاربر برای مجازات پیدا نشد: "
            f"user_id={user_id}"
        )
        return
    
    try:
        chat = await event.get_chat()

        is_admin = await is_chat_admin(
            self.client,
            chat,
            user_id,
            raise_on_error=True,
        )

    except Exception as exc:
        print(
            f"⚠️ پردازش درخواست مجازات متوقف شد: {exc}"
        )
        return

    # ادمین‌ها مجازات نمی‌شوند.
    if is_admin:
        return

    settings = await self.settings.get(
        group_id
    )

    # همان throttle فعلی سیستم مجازات.
    if not punishment_throttle.should_punish(
        group_id,
        user_id,
        10,
    ):
        return

    punishment_text = None

    try:

        if settings["punishment_type"] == "ban":
            try:
                await moderation.ban_user(
                    self.client,
                    chat,
                    target_entity,
                )

            except moderation.ModerationError as exc:
                await _safe_reply(
                    event,
                    str(exc),
                )
                return
                
            punishment_text = (
                "🔨 مجازات: کاربر بن شد."
            )

        elif settings["punishment_type"] == "mute":

            hours = settings[
                "mute_hours"
            ]

            try:
                await moderation.mute_user(
                    self.client,
                    chat,
                    target_entity,
                    hours=hours,
                )

            except moderation.ModerationError as exc:
                await _safe_reply(
                    event,
                    str(exc),
                )
                return
            


            
            if hours is None:
                punishment_text = (
                    "🔇 مجازات: کاربر "
                    f"به‌صورت دائمی میوت شد.\nبرای لغو این عمل از این دستور استفاده کنید:\n`آنمیوت {user_id}!`\n(توجه:علامت تعجب '!' باید اول دستور باشد)"
                )

            else:
                punishment_text = (
                    "🔇 مجازات: کاربر میوت شد "
                    f"({hours} ساعت).\nبرای لغو این عمل از این دستور استفاده کنید:\n`آنمیوت {user_id}!`\n(توجه:علامت تعجب '!' باید اول دستور باشد)"
                    
                )

        else:
            print(
                "⚠️ نوع مجازات ناشناخته است: "
                f"{settings['punishment_type']}"
            )

            return

    except Exception as exc:

        print(
            f"❌ اعمال مجازات ناموفق بود: {exc}"
        )

        return

    punishment_throttle.mark_punished(
        group_id,
        user_id,
        10,
    )

    name = await _display_name(
        event,
        user_id,
    )

    message = (
        f"⚠️ {name} به‌دلیل تخلف مکرر مجازات شد.\n"
        f"📌 دلیل: {reason}\n"
        f"{punishment_text}"
    )

    if self.notice_throttle.should_notify(
        group_id,
        user_id,
        source or reason,
    ):
        await _notify(
            event,
            message,
        )

@on_bus_event("violation")
async def on_violation(
    self: "ViolationManagerPlugin",
    event,
    group_id: int,
    user_id: int,
    reason: str,
    message_ids: list[int] | None = None,
    spam_type: str | None = None,
    violation_score: int = 1,
    confidence: int = 0,
    source: str = "unknown",
) -> None:

    violation_score = (
        _normalize_violation_score(
            violation_score
        )
    )

    confidence = max(
        0,
        min(
            100,
            int(confidence),
        ),
    )




    # 0 یعنی اصلاً violation نیست.
    if violation_score <= 0:
        return

    try:
        chat = await event.get_chat()

        is_admin = await is_chat_admin(
            self.client,
            chat,
            user_id,
            raise_on_error=True,
        )

    except Exception as exc:
        print(
            f"⚠️ پردازش تخلف متوقف شد: {exc}"
        )
        return

    # ادمین‌ها مجازات نمی‌شوند.
    if is_admin:
        return
    
    target_entity = (
        await moderation.resolve_user_entity(
            self.client,
            event,
            user_id,
        )
    )

    if target_entity is None:
        print(
            "⚠️ Entity کاربر برای اعمال مجازات پیدا نشد: "
            f"user_id={user_id}"
        )
        return
    # ---------------------------------------------
    # اول همیشه سابقه را ثبت کن.
    # ---------------------------------------------

    await self.violations.add(
        group_id,
        user_id,
        reason,
        severity=violation_score,
        source=source,
        confidence=confidence,
    )

    # ---------------------------------------------
    # تخلف ضعیف فقط سابقه است.
    # ---------------------------------------------

    if violation_score < 7:
        return

    # ---------------------------------------------
    # از اینجا به بعد violation قطعی است.
    # نوع مجازات = انتخاب ادمین
    # ---------------------------------------------

    settings = await self.settings.get(
        group_id
    )

    if not punishment_throttle.should_punish(
        group_id,
        user_id,
        violation_score,
    ):
        return

    punishment_text = None

    try:

        if settings["punishment_type"] == "ban":
            try:
                await moderation.ban_user(
                    self.client,
                    chat,
                    target_entity,
                )

            except moderation.ModerationError as exc:
                await _safe_reply(
                    event,
                    str(exc),
                )
                return
            
            punishment_text = (
                "🔨 مجازات: کاربر بن شد."
            )

        elif settings["punishment_type"] == "mute":

            hours = settings[
                "mute_hours"
            ]

            try:
                await moderation.mute_user(
                    self.client,
                    chat,
                    target_entity,
                    hours=hours,
                )

            except moderation.ModerationError as exc:
                await _safe_reply(
                    event,
                    str(exc),
                )
                return
    
            if hours is None:
                punishment_text = (
                    "🔇 مجازات: کاربر "
                    "به‌صورت دائمی میوت شد.\n"
                    f"برای لغو این دستور را بزنید: `!آنمیوت {user_id}`"
                )

            else:
                punishment_text = (
                    "🔇 مجازات: کاربر میوت شد "
                    f"({hours} ساعت).\n"
                    f"برای لغو این دستور را بزنید: `!آنمیوت {user_id}`"

                )

        else:
            print(
                "⚠️ نوع مجازات ناشناخته است: "
                f"{settings['punishment_type']}"
            )

            return

    except Exception as exc:

        print(
            f"❌ اعمال مجازات ناموفق بود: {exc}"
        )

        return
    punishment_throttle.mark_punished(
        group_id,
        user_id,
        violation_score,
    )
    name = await _display_name(
        event,
        user_id,
    )

    message = (
        f"⚠️ {name} اسپم کرده.\n"
        f"📌 دلیل: "
        f"{spam_type or reason}\n"
        f"🎯 اطمینان: "
        f"{confidence}/100\n"
        f"{punishment_text}"
    )

    if self.notice_throttle.should_notify(
        group_id,
        user_id,
        spam_type or reason,
    ):
        sent = await _notify(
            event,
            message,
        )

        if sent is not None:
            await self.event_bus.emit(
                "timeline_system_message",
                group_id=group_id,
                message=sent,
            )