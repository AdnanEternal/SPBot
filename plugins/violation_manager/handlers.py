from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_bus_event, on_event
from core.permissions import is_chat_admin

from . import moderation

# فقط برای type checker ایمپورت می‌شه، موقع اجرا نه؛ اینجوری import
# چرخه‌ای (handlers.py <-> plugin.py) پیش نمیاد.
if TYPE_CHECKING:
    from .plugin import ViolationManagerPlugin

# اگه مدت میوتِ گروه هنوز تنظیم نشده باشه (نه با !مجازات میوت، نه با
# مجازات خودکار)، از این مقدار برای !میوت دستی استفاده می‌شه.
DEFAULT_MUTE_HOURS = 1




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
    description="مجازات خودکارِ این گروه رو میوت می‌ذاره و مدتش (به ساعت) رو تنظیم می‌کنه.",
)
async def set_punishment_mute(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    value = event.args_text.strip()
    if not value.isdigit() or int(value) <= 0:
        await event.reply("مثال: !مجازات میوت 6")
        return

    hours = int(value)
    await self.settings.set_punishment_mute(event.chat_id, hours)
    await event.reply(f"زمان مجازات میوت کردن با موفقیت به {hours} ساعت اپدیت شد!")


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
    permission="admin",
    chat_type="group",
    description="یه کاربر رو میوت می‌کنه (با یوزرنیم یا ریپلای روی پیامش)، حتی اگه تخلفی نکرده باشه.",
)
async def mute_command(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    target_id = await moderation.resolve_target(self.client, event)
    if target_id is None:
        await event.reply("مثال: !میوت @username یا روی پیام شخص ریپلای کن.")
        return

    settings = await self.settings.get(event.chat_id)
    hours = settings["mute_hours"] or DEFAULT_MUTE_HOURS

    chat = await event.get_chat()
    await moderation.mute_user(self.client, chat, target_id, hours)
    await event.reply(f"کاربر `{target_id}` به مدت {hours} ساعت میوت شد.")


@command(
    name="آنمیوت",
    permission="admin",
    chat_type="group",
    description="میوتِ یه کاربر رو برمی‌داره (با یوزرنیم یا ریپلای روی پیامش).",
)
async def unmute_command(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    target_id = await moderation.resolve_target(self.client, event)
    if target_id is None:
        await event.reply("مثال: !آنمیوت @username یا روی پیام شخص ریپلای کن.")
        return

    chat = await event.get_chat()
    await moderation.unmute_user(self.client, chat, target_id)
    await event.reply(f"میوتِ کاربر `{target_id}` برداشته شد.")


@on_event(events.NewMessage(incoming=True))
async def on_reply_shortcut(self: "ViolationManagerPlugin", event: events.NewMessage.Event) -> None:
    """
    میان‌بر: به‌جای !میوت/!آنمیوت، فقط با ریپلای‌کردن روی پیام شخص و
    نوشتن کلمه‌ی «میوت» یا «آنمیوت» (بدون ! و بدون یوزرنیم) هم می‌شه
    همون کار رو کرد.

    این یه هندلر رویداد خام هست (نه کامند)، چون متن با ! شروع نمی‌شه و
    از دیسپچر command_manager رد نمی‌شه؛ برای همین permission رو خودمون
    این‌جا دستی چک می‌کنیم.
    """
    if not event.is_group or not event.is_reply:
        return

    text = (event.raw_text or "").strip()
    if text not in ("میوت", "آنمیوت"):
        return

    chat = await event.get_chat()
    if not await is_chat_admin(self.client, chat, event.sender_id):
        return

    reply = await event.get_reply_message()
    if reply is None:
        return
    target_id = reply.sender_id

    if text == "میوت":
        settings = await self.settings.get(event.chat_id)
        hours = settings["mute_hours"] or DEFAULT_MUTE_HOURS
        await moderation.mute_user(self.client, chat, target_id, hours)
        await event.reply(f"کاربر `{target_id}` به مدت {hours} ساعت میوت شد.")
    else:
        await moderation.unmute_user(self.client, chat, target_id)
        await event.reply(f"میوتِ کاربر `{target_id}` برداشته شد.")


@on_bus_event("violation")
async def on_violation(
    self: "ViolationManagerPlugin",
    event,
    group_id: int,
    user_id: int,
    reason: str,
) -> None:
    """
    دریافت گزارش تخلف از سایر پلاگین‌ها.

    اگر کاربر ادمین باشد:
    - پیام قبلاً توسط پلاگین مربوطه حذف شده است.
    - سابقه‌ی تخلف ثبت نمی‌شود.
    - شمارنده افزایش پیدا نمی‌کند.
    - مجازات خودکار اعمال نمی‌شود.

    کاربران عادی طبق سیستم معمول ثبت و مجازات می‌شوند.
    """

    # بررسی ادمین بودن کاربر
    chat = await event.get_chat()

    if await is_chat_admin(
        self.client,
        chat,
        user_id,
    ):
        await event.reply(
            f"⚠️ {event.sender.username or event.sender.first_name} "
            f"مرتکب تخلف شد.\n"
            f"📌 دلیل: {reason}\n"
    )

    # -----------------------------
    # کاربر عادی
    # -----------------------------

    await self.violations.add(
        group_id,
        user_id,
        reason,
    )

    count = await self.violations.get_count(
        group_id,
        user_id,
    )

    settings = await self.settings.get(group_id)

    await event.reply(
        f"⚠️ {event.sender.username or event.sender.first_name} "
        f"مرتکب تخلف شد.\n"
        f"📌 دلیل: {reason}\n"
        f"🔢 تعداد تخلفات: {count}\n"
        f"🚫 سقف مجاز تخلف: {settings['max_violations']}"
    )

    if count <= settings["max_violations"]:
        return

    if settings["punishment_type"] == "ban":
        await moderation.ban_user(
            self.client,
            group_id,
            user_id,
        )

    elif settings["punishment_type"] == "mute":
        hours = (
            settings["mute_hours"]
            or DEFAULT_MUTE_HOURS
        )

        await moderation.mute_user(
            self.client,
            group_id,
            user_id,
            hours,
        )