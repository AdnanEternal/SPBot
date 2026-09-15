



from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command

# فقط برای type checker ایمپورت می‌شه، موقع اجرا نه؛ اینجوری import
# چرخه‌ای (handlers.py <-> plugin.py) پیش نمیاد.
if TYPE_CHECKING:
    from .plugin import ViolationManagerPlugin



@command(
    name="لیست متخلفان",
    permission="admin",
    chat_type="group",
    description="📋لیست کاربران متخلف این گروه رو نشون می‌ده.",
)
async def list_violators(
    self: "ViolationManagerPlugin",
    event: events.NewMessage.Event,
) -> None:
    users = await self.violations.get_users(event.chat_id)

    if not users:
        await event.reply("✅ هیچ کاربر متخلفی در این گروه ثبت نشده.")
        return

    lines = [
        f"👤 `{row['user_id']}` — ⚠️ {row['violation_count']} تخلف"
        for row in users
    ]

    response_text = "⚠️ کاربران متخلف این گروه:\n\n" + "\n".join(lines)

    await event.reply(response_text)