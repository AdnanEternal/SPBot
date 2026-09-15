from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_event

# فقط برای type checker ایمپورت می‌شه، موقع اجرا نه؛ اینجوری import
# چرخه‌ای (handlers.py <-> plugin.py) پیش نمیاد.
if TYPE_CHECKING:
    from .plugin import ContentFilterPlugin


@command(
    name="فیلتر",
    permission="admin",
    chat_type="group",
    description="یک کلمه رو به لیست فیلتر این گروه اضافه می‌کنه.",
)
async def add_word(self: "ContentFilterPlugin", event: events.NewMessage.Event) -> None:
    word = event.args_text
    if not word:
        await event.reply("مثال: !فیلتر کلمه")
        return

    await self.words.add(event.chat_id, word)
    await event.reply(f"کلمه «{word}» به لیست فیلتر این گروه اضافه شد.")


@command(
    name="حذف فیلتر",
    permission="admin",
    chat_type="group",
    description="یک کلمه رو از لیست فیلتر این گروه حذف می‌کنه.",
)
async def remove_word(self: "ContentFilterPlugin", event: events.NewMessage.Event) -> None:
    word = event.args_text
    if not word:
        await event.reply("مثال: !حذف فیلتر کلمه")
        return

    await self.words.remove(event.chat_id, word)
    await event.reply(f"کلمه «{word}» از لیست فیلتر این گروه حذف شد.")


@command(
    name="لیست فیلتر",
    permission="admin",
    chat_type="group",
    description="لیست کلمات فیلترشده‌ی این گروه رو نشون می‌ده.",
)
async def list_words(self: "ContentFilterPlugin", event: events.NewMessage.Event) -> None:
    words = await self.words.get_all(event.chat_id)
    if not words:
        await event.reply("لیست فیلتر این گروه خالیه.")
        return

    await event.reply("کلمات فیلترشده:\n" + "\n".join(sorted(words)))


@on_event(events.NewMessage(incoming=True))
async def on_message(self: "ContentFilterPlugin", event: events.NewMessage.Event) -> None:
    if not event.is_group:
        return

    if await self.words.contains(event.chat_id, event.raw_text or ""):
        await event.delete()

        # به‌جای اینکه مستقیماً بریم سراغ violation_manager (که یعنی
        # بهش وابسته بشیم)، فقط رو event_bus اعلام می‌کنیم که یه تخلف
        # رخ داد. اگه violation_manager نصب/فعال نباشه، این خط کاملاً
        # بی‌اثره و خطایی نمی‌ده.
        await self.event_bus.emit(
            "violation",
            group_id=event.chat_id,
            user_id=event.sender_id,
            reason="استفاده از کلمه‌ی فیلترشده",
        )