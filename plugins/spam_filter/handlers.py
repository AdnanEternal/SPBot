from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_event
from core.permissions import is_chat_admin

from . import detection

# فقط برای type checker ایمپورت می‌شه، موقع اجرا نه؛ اینجوری import
# چرخه‌ای (handlers.py <-> plugin.py) پیش نمیاد.
if TYPE_CHECKING:
    from .plugin import SpamFilterPlugin


def _is_remote_group_id(
    value: str,
) -> bool:
    if not value:
        return False

    try:
        return int(value) < 0
    except ValueError:
        return False


def _extract_optional_group_target(
    raw: str,
) -> tuple[int | None, str]:
    parts = raw.strip().split()

    if not parts:
        return None, ""

    candidate = parts[-1]

    if not _is_remote_group_id(candidate):
        return None, raw.strip()

    return (
        int(candidate),
        " ".join(parts[:-1]).strip(),
    )


def _resolve_spam_group_target(
    event,
) -> tuple[int | None, str]:
    raw = (
        event.args_text or ""
    ).strip()

    target_group, clean_args = (
        _extract_optional_group_target(
            raw
        )
    )

    if target_group is not None:
        return target_group, clean_args

    if event.is_group:
        return event.chat_id, clean_args

    return None, clean_args



@command(
    name="اسپم معاف",
    permission="admin",
    chat_type="all",
    description="یک کاربر را از Spam Filter معاف می‌کند.",
)
async def add_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!اسپم معاف 49245702 -10024473944"
        )
        return

    if not args.isdigit():
        await event.reply(
            "❌ شناسه کاربر باید عددی باشد.\n"
            "مثال:\n"
            "!اسپم معاف 49245702"
        )
        return

    user_id = int(args)

    added = await self.whitelist.add(
        target_group,
        user_id,
    )

    if not added:
        await event.reply(
            f"ℹ️ کاربر `{user_id}` از قبل "
            f"از Spam Filter معاف است."
        )
        return

    await event.reply(
        f"✅ کاربر `{user_id}` از Spam Filter "
        f"گروه `{target_group}` معاف شد."
    )


@command(
    name="اسپم رفع معافیت",
    permission="admin",
    chat_type="all",
    description="معافیت یک کاربر از Spam Filter را لغو می‌کند.",
)
async def remove_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!اسپم رفع معافیت 49245702 -10024473944"
        )
        return

    if not args.isdigit():
        await event.reply(
            "❌ شناسه کاربر باید عددی باشد.\n"
            "مثال:\n"
            "!اسپم رفع معافیت 49245702"
        )
        return

    user_id = int(args)

    removed = await self.whitelist.remove(
        target_group,
        user_id,
    )

    if not removed:
        await event.reply(
            f"ℹ️ کاربر `{user_id}` در لیست معافیت "
            f"وجود ندارد."
        )
        return

    await event.reply(
        f"✅ معافیت کاربر `{user_id}` از Spam Filter "
        f"لغو شد."
    )


@command(
    name="اسپم معاف ها",
    permission="admin",
    chat_type="all",
    description="لیست کاربران معاف از Spam Filter را نشان می‌دهد.",
)
async def list_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!اسپم معاف ها -10024473944"
        )
        return

    if args:
        await event.reply(
            "❌ استفاده نادرست.\n"
            "مثال:\n"
            "!اسپم معاف ها\n"
            "یا:\n"
            "!اسپم معاف ها -10024473944"
        )
        return

    users = await self.whitelist.get_all(
        target_group
    )

    if not users:
        await event.reply(
            f"📋 لیست معافیت Spam Filter گروه "
            f"`{target_group}` خالی است."
        )
        return

    lines = [
        f"• `{user_id}`"
        for user_id in users
    ]

    await event.reply(
        f"📋 کاربران معاف از Spam Filter\n"
        f"گروه: `{target_group}`\n\n"
        + "\n".join(lines)
    )




@command(
    name="اسپم فلاد",
    permission="admin",
    chat_type="group",
    description="حداکثر تعداد پیام مجاز در یه بازه‌ی زمانی رو تنظیم می‌کنه. مثال: !اسپم فلاد 5 10",
)
async def set_flood(self: "SpamFilterPlugin", event: events.NewMessage.Event) -> None:
    parts = event.args_text.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await event.reply("مثال: !اسپم فلاد 5 10  (یعنی بیشتر از ۵ پیام تو ۱۰ ثانیه = اسپم)")
        return

    count, seconds = int(parts[0]), int(parts[1])
    await self.settings.set_flood(event.chat_id, count, seconds)
    await event.reply(f"آستانه‌ی فلاد با موفقیت روی «بیشتر از {count} پیام در {seconds} ثانیه» تنظیم شد!")


@command(
    name="اسپم لینک",
    permission="admin",
    chat_type="group",
    description="حداکثر تعداد لینک مجاز تو یه پیام رو تنظیم می‌کنه.",
)
async def set_max_links(self: "SpamFilterPlugin", event: events.NewMessage.Event) -> None:
    value = event.args_text.strip()
    if not value.isdigit():
        await event.reply("مثال: !اسپم لینک 3")
        return

    await self.settings.set_max_links(event.chat_id, int(value))
    await event.reply(f"حداکثر لینک مجاز تو هر پیام با موفقیت به {value} تنظیم شد!")


@command(
    name="اسپم تکرار",
    permission="admin",
    chat_type="group",
    description="حداکثر تعداد پیام تکراریِ پشت‌سرهم مجاز رو تنظیم می‌کنه.",
)
async def set_max_repeat(self: "SpamFilterPlugin", event: events.NewMessage.Event) -> None:
    value = event.args_text.strip()
    if not value.isdigit():
        await event.reply("مثال: !اسپم تکرار 3")
        return

    await self.settings.set_max_repeat(event.chat_id, int(value))
    await event.reply(f"حداکثر پیام تکراری مجاز با موفقیت به {value} تنظیم شد!")


@command(
    name="تنظیمات اسپم",
    permission="admin",
    chat_type="group",
    description="تنظیمات فعلی فیلتر اسپم این گروه رو نشون می‌ده.",
)
async def show_settings(self: "SpamFilterPlugin", event: events.NewMessage.Event) -> None:
    s = await self.settings.get(event.chat_id)
    await event.reply(
        "⚙️ تنظیمات فیلتر اسپم این گروه:\n\n"
        f"فلاد: بیشتر از {s['flood_count']} پیام در {s['flood_seconds']} ثانیه\n"
        f"لینک: بیشتر از {s['max_links']} لینک تو یه پیام\n"
        f"تکرار: بیشتر از {s['max_repeat']} پیام یکسان پشت‌سرهم"
    )


async def _flag(self: "SpamFilterPlugin", event: events.NewMessage.Event, reason: str) -> None:
    """
    یه پیام رو اسپم اعلام می‌کنه: پاکش می‌کنه و رو event_bus رویداد
    violation منتشر می‌کنه (همون مکانیزمی که content_filter هم استفاده
    می‌کنه). خطای احتمالی موقع پاک‌کردن (مثلاً نبود دسترسی حذف) نباید
    کل هندلر رو متوقف کنه، برای همین try/except داره.
    """
    try:
        await event.delete()
    except Exception as e:
        print(f"⚠️ نتونستم پیام اسپم رو پاک کنم: {e}")

    await self.event_bus.emit(
        "violation",
        event=event,
        group_id=event.chat_id,
        user_id=event.sender_id,
        reason=f"اسپم: {reason}",
    )


async def _flag_flood(self: "SpamFilterPlugin", event: events.NewMessage.Event, window_seconds: int) -> None:
    ids = self.tracker.ids_in_window(event.chat_id, event.sender_id, window_seconds)

    # پیام‌های این بازه نباید دوباره شمرده بشن
    self.tracker.clear_user(event.chat_id, event.sender_id)

    try:
        chat = await event.get_chat()
        await self.client.delete_messages(chat, ids)
    except Exception as e:
        print(f"⚠️ نتونستم پیام‌های فلاد رو پاک کنم: {e}")

    await self.event_bus.emit(
        "violation",
        event=event,
        group_id=event.chat_id,
        user_id=event.sender_id,
        reason=(
            f"اسپم: ارسال بیش از حد پیام "
            f"در {window_seconds} ثانیه (فلاد)"
        ),
        message_ids=ids,
    )


@on_event(events.NewMessage(incoming=True))
async def on_message(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:

    if (
        not event.is_group
        or event.sender_id is None
    ):
        return

    # کاربران موجود در Spam Whitelist باید کاملاً
    # از Spam Filter عبور کنند و حتی وارد tracker هم نشوند.
    if await self.whitelist.is_exempt(
        event.chat_id,
        event.sender_id,
    ):
        return

    text = event.raw_text or ""

    settings = await self.settings.get(
        event.chat_id
    )

    repeat_count = self.tracker.register(
        event.chat_id,
        event.sender_id,
        event.id,
        text,
    )

    reason = None
    is_flood = False

    link_count = detection.count_links(
        text
    )

    if link_count > settings["max_links"]:
        reason = (
            "بیش از حدِ مجاز لینک تو یه پیام "
            f"({link_count} لینک)"
        )

    elif repeat_count > settings["max_repeat"]:
        reason = (
            "ارسال پیام تکراری پشت‌سرهم"
        )

    elif detection.has_char_flood(text):
        reason = (
            "تکرار بیش‌ازحد یه کاراکتر تو پیام"
        )

    elif (
        self.tracker.count_in_window(
            event.chat_id,
            event.sender_id,
            settings["flood_seconds"],
        )
        > settings["flood_count"]
    ):
        is_flood = True

    # پیام عادی:
    # بدون API call و بدون permission check
    if reason is None and not is_flood:
        return

    # فقط پیام مشکوک به اینجا می‌رسد.
    try:
        chat = await event.get_chat()

        if await is_chat_admin(
            self.client,
            chat,
            event.sender_id,
            raise_on_error=True,
        ):
            self.tracker.clear_user(
                event.chat_id,
                event.sender_id,
            )
            return

    except Exception:
        # وقتی مطمئن نیستیم ادمین نیست،
        # مجازات نکن.
        return

    if is_flood:
        await _flag_flood(
            self,
            event,
            settings["flood_seconds"],
        )
        return

    await _flag(
        self,
        event,
        reason,
    )