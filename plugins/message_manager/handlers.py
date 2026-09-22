import random

from typing import TYPE_CHECKING

from splusthon import events
from splusthon.tl import types, functions

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

    # =========================================================
    # اجرای ریموت
    # =========================================================
    if event.id is None:
        # آخرین پیام گروه را از Dialog می‌گیریم.
        # این مسیر از GetHistory/Search استفاده نمی‌کند.
        dialog_result = await self.client(
            functions.messages.GetPeerDialogsRequest(
                [
                    types.InputDialogPeer(chat)
                ]
            )
        )

        if not dialog_result.dialogs:
            await event.reply(
                "❌ گروه هدف در لیست گفتگوهای ربات پیدا نشد."
            )
            return

        top_message_id = dialog_result.dialogs[0].top_message

        if not top_message_id:
            await event.reply(
                "❌ این گروه هنوز پیامی ندارد."
            )
            return

        # آخرین N شناسه پیام
        first_message_id = max(
            1,
            top_message_id - count + 1,
        )

        requested_ids = list(
            range(
                first_message_id,
                top_message_id + 1,
            )
        )

        # چون ids داده شده، SPlusthon از
        # GetMessagesRequest استفاده می‌کند،
        # نه GetHistoryRequest و نه SearchRequest.
        messages = await self.client.get_messages(
            chat,
            ids=requested_ids,
        )

        message_ids = [
            message.id
            for message in messages
            if message is not None
            and message.id is not None
        ]

        if not message_ids:
            await event.reply(
                "❌ پیامی برای پاکسازی پیدا نشد."
            )
            return

        await self.client.delete_messages(
            chat,
            message_ids,
        )

        return

    # =========================================================
    # اجرای عادی داخل گروه
    # =========================================================
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
        await event.reply(
            "❌ پیامی برای پاکسازی پیدا نشد."
        )
        return

    await self.client.delete_messages(
        chat,
        message_ids,
    )

    await event.delete()
    
@on_event(events.NewMessage(incoming=True))
async def meow_trigger(
    self: "MessageManagerPlugin",
    event: events.NewMessage.Event,
) -> None:
    if (event.raw_text or "").strip() != "میو":
        return

    await event.reply(random.choice(MEOW_RESPONSES))