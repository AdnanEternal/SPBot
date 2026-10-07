from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command


if TYPE_CHECKING:
    from .plugin import AntiSleepPlugin


@command(
    name="ضد خاموشی",
    permission="owner",
    chat_type="group",
    description=(
        "ربات را در همین گروه با heartbeat "
        "تصادفی بین 1 تا 15 دقیقه فعال نگه می‌دارد."
    ),
)
async def enable_anti_sleep(
    self: "AntiSleepPlugin",
    event: events.NewMessage.Event,
) -> None:
    await self.store.enable(
        chat_id=event.chat_id,
        interval_minutes=1,
    )

    await self.start_heartbeat()

    await event.reply(
        "✅ سیستم مقابله با خاموشی فعال شد.\n"
        "📍 مقصد: همین گروه\n"
        "🎲 فاصله: تصادفی بین 1 تا 15 دقیقه\n"
        "🔗 در هر heartbeat، GitHub بررسی و نتیجه ارسال می‌شود."
    )