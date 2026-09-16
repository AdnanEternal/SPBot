from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command

from .github_manager.manager import GitHubManager
from .backup.backup import DatabaseBackupManager

if TYPE_CHECKING:
    from .plugin import SystemPlugin


@command(
    name="راهنما",
    permission="everyone",
    chat_type="all",
    description="❓لیست همه‌ی کامندهای ربات رو نشون می‌ده.",
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
        f"`!{cmd.name}`:\n{cmd.description or 'بدون توضیح'}\n"
        for cmd in commands
    ]

    await event.reply("📖لیست کامندها:\n" + "\n".join(lines))







@command(
    name="گیتهاب چک",
    permission="admin",
    chat_type="group",
    description="🔗 اتصال ربات به مخزن GitHub را بررسی می‌کند.",
)
async def github_check(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    try:
        github = GitHubManager()
        await github.check_connection()

    except Exception as e:
        await event.reply(f"❌ اتصال به GitHub ناموفق بود.\n`{e}`")
        return

    await event.reply("✅ اتصال به GitHub با موفقیت برقرار شد.")


@command(
    name="دیتابیس بکاپ",
    permission="admin",
    chat_type="all",
    description="💾 یک نسخه از دیتابیس را در GitHub ذخیره می‌کند.",
)
async def database_backup(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    try:
        github = GitHubManager()
        backup = DatabaseBackupManager(
            db=self.db,
            github=github,
        )

        await backup.create_backup()

    except Exception as e:
        await event.reply(f"❌ بکاپ دیتابیس ناموفق بود.\n`{e}`")
        return

    await event.reply("✅ بکاپ دیتابیس با موفقیت در GitHub ذخیره شد.")



@command(
    name="دیتابیس بازیابی",
    permission="everyone",
    chat_type="all",
    description="♻️ دیتابیس را از آخرین بکاپ GitHub بازیابی می‌کند.",
)
async def database_restore(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    try:
        github = GitHubManager()

        backup = DatabaseBackupManager(
            db=self.db,
            github=github,
        )

        await backup.restore_backup()

    except Exception as e:
        await event.reply(
            f"❌ بازیابی دیتابیس ناموفق بود.\n`{e}`"
        )
        return

    await event.reply(
        "✅ دیتابیس با موفقیت از آخرین بکاپ GitHub بازیابی شد."
    )