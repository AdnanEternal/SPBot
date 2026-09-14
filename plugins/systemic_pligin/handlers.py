from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command

if TYPE_CHECKING:
    from .plugin import SystemPlugin


@command(
    name="راهنما",
    permission="everyone",
    chat_type="all",
    description="لیست همه‌ی کامندهای ربات رو نشون می‌ده.",
)
async def show_help(self: "SystemPlugin", event: events.NewMessage.Event) -> None:
    # get_all_commands() یه متد عمومی روی command_manager (زیرساخت core)ه؛
    # این‌جا فقط داریم ازش می‌خونیم، هیچ دونشی درباره‌ی پلاگین‌های دیگه
    # مستقیماً وارد این پلاگین نمی‌شه.
    commands = sorted(self.command_manager.get_all_commands(), key=lambda c: c.name)

    if not commands:
        await event.reply("هنوز هیچ کامندی ثبت نشده.")
        return

    lines = [
        f"!{cmd.name} — {cmd.description or 'بدون توضیح'}"
        for cmd in commands
    ]

    await event.reply("لیست کامندها:\n" + "\n".join(lines))