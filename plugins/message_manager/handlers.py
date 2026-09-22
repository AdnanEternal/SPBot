import random

from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_event

if TYPE_CHECKING:
    from .plugin import MessageManagerPlugin

MAX_CLEAR_COUNT = 400

MEOW_RESPONSES = [
    "😺",
    "اخجون گربه!",
    "حالت خوبه؟ نکنه گربه گازت گرفته داری گربه میشی؟ 🐈",
    "میووو 😸",
    "یکی اینجا گربه شد؟ 🐈",
    "میو؟ 🤨",
    "گربه شناسایی شد! 🚨🐈",
]


@command(
    "پاکسازی",
    permission="admin",
    chat_type="group",
    description="🧹 پاکسازی دسته‌جمعی پیام‌های اخیر",
)
async def clear_messages(
    self: "MessageManagerPlugin",
    event: events.NewMessage.Event,
) -> None:
    if not event.args:
        await event.reply("مثال: !پاکسازی 20")
        return

    count_text = event.args[0]

    if not count_text.isdigit():
        await event.reply("❌ تعداد پیام‌ها باید یک عدد باشد.")
        return

    count = int(count_text)

    if count <= 0:
        await event.reply("❌ تعداد پیام‌ها باید بیشتر از صفر باشد.")
        return

    if count > MAX_CLEAR_COUNT:
        await event.reply(
            f"❌ حداکثر تعداد پاکسازی در هر بار {MAX_CLEAR_COUNT} پیام است."
        )
        return

    chat = await event.get_chat()

    # اجرای ریموت:
    # در گروه پیام فیزیکیِ کامند وجود ندارد، پس N پیام آخر را پاک می‌کنیم.
    if event.id is None:
        messages = await self.client.get_messages(
            chat,
            limit=count,
            search=""
        )

        message_ids = [
            message.id
            for message in messages
            if message.id is not None
        ]

        if not message_ids:
            await event.reply("❌ پیامی برای پاکسازی پیدا نشد.")
            return

        await self.client.delete_messages(
            chat,
            message_ids,
        )

        return

    # اجرای عادی داخل گروه:
    messages = await self.client.get_messages(
        chat,
        limit=count + 1,
    )

    message_ids = [
        message.id
        for message in messages
        if message.id != event.id
    ]

    if not message_ids:
        await event.reply("❌ پیامی برای پاکسازی پیدا نشد.")
        return

    await self.client.delete_messages(
        chat,
        message_ids,
    )

    # خود پیام کامند هم حذف شود.
    await event.delete()


@on_event(events.NewMessage(incoming=True))
async def meow_trigger(
    self: "MessageManagerPlugin",
    event: events.NewMessage.Event,
) -> None:
    if (event.raw_text or "").strip() != "میو":
        return

    await event.reply(random.choice(MEOW_RESPONSES))