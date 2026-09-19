from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command

if TYPE_CHECKING:
    from .plugin import AntiSleepPlugin


@command(
    name="مقابله با خاموشی در همین گروه",
    permission="owner",
    chat_type="group",
    description=(
        "ربات را هر 25 دقیقه در همین گروه فعال نگه می‌دارد."
    ),
)
async def enable_anti_sleep(
    self: "AntiSleepPlugin",
    event: events.NewMessage.Event,
) -> None:
    await self.store.enable(
        chat_id=event.chat_id,
        interval_minutes=25,
    )

    await self.start_heartbeat()

    await event.reply(
        "✅ سیستم مقابله با خاموشی فعال شد.\n"
        "📍 مقصد: همین گروه\n"
        "⏱ فاصله: 25 دقیقه"
    )