from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_event

if TYPE_CHECKING:
    from .plugin import ContentFilterPlugin


@command(
    name="فیلتر",
    permission="admin",
    chat_type="group",
    description="یک کلمه رو به لیست فیلتر این گروه اضافه می‌کنه.",
)
async def add_word(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    word = event.args_text.strip()

    if not word:
        await event.reply("مثال: !فیلتر کلمه")
        return

    await self.words.add(event.chat_id, word)

    await event.reply(
        f"کلمه «{word}» به لیست فیلتر این گروه اضافه شد."
    )


@command(
    name="حذف فیلتر",
    permission="admin",
    chat_type="group",
    description="یک کلمه رو از لیست فیلتر این گروه حذف می‌کنه.",
)
async def remove_word(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    word = event.args_text.strip()

    if not word:
        await event.reply("مثال: !حذف فیلتر کلمه")
        return

    removed = await self.words.remove(
        event.chat_id,
        word,
    )

    if removed:
        await event.reply(
            f"کلمه «{word}» از لیست فیلتر این گروه حذف شد."
        )
    else:
        await event.reply(
            f"کلمه «{word}» در لیست فیلتر این گروه وجود نداشت."
        )


@command(
    name="لیست فیلتر",
    permission="admin",
    chat_type="group",
    description="لیست کلمات فیلترشده‌ی این گروه رو نشون می‌ده.",
)
async def list_words(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    words = await self.words.get_all(event.chat_id)

    if not words:
        await event.reply("لیست فیلتر این گروه خالیه.")
        return

    await event.reply(
        "کلمات فیلترشده:\n" +
        "\n".join(sorted(words))
    )


@on_event(events.NewMessage(incoming=True))
async def on_message(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    if not event.is_group:
        return

    text = event.raw_text or ""

    matched_word = await self.words.find_match(
        event.chat_id,
        text,
    )

    if matched_word is None:
        return

    # پیام همیشه حذف می‌شود؛ حتی اگر فرستنده ادمین باشد.
    await event.delete()

    # دلیل دقیق تخلف را برای Violation Manager می‌فرستیم.
    await self.event_bus.emit(
        event_name="violation",
        event=event,
        group_id=event.chat_id,
        user_id=event.sender_id,
        reason=f"استفاده از کلمه ||{matched_word}|| ممنوع است.",
    )