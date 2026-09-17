from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command
from core.permissions import is_chat_admin, is_owner

from .backup.backup import DatabaseBackupManager
from .github_manager.manager import GitHubManager
from .plugin_updater import PluginUpdateManager

if TYPE_CHECKING:
    from .plugin import SystemPlugin

HELP_PAGE_SIZE = 6


@command(
    name="راهنما",
    permission="everyone",
    chat_type="all",
    description="❓لیست کامندهای قابل استفاده را نشان می‌دهد.",
)
async def show_help(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    sender_id = event.sender_id
    is_owner_user = is_owner(sender_id)

    # داخل گروه بررسی می‌کنیم کاربر ادمین هست یا نه.
    is_admin_user = False

    if event.is_group:
        chat = await event.get_chat()
        is_admin_user = await is_chat_admin(
            self.client,
            chat,
            sender_id,
        )

    # تعیین می‌کنیم چه سطح دسترسی‌هایی قابل نمایش باشند.
    if is_owner_user:
        allowed_permissions = {"everyone", "admin", "owner"}

    elif event.is_private:
        allowed_permissions = {"everyone", "admin"}

    elif is_admin_user:
        allowed_permissions = {"everyone", "admin"}

    elif is_admin_user:
        allowed_permissions = {"everyone", "admin"}

    else:
        allowed_permissions = {"everyone"}

    commands = [
        cmd
        for cmd in self.command_manager.get_all_commands()
        if cmd.permission in allowed_permissions
    ]

    commands.sort(key=lambda cmd: cmd.name)

    if not commands:
        await event.reply("📖 هیچ کامندی برای نمایش وجود ندارد.")
        return

    # صفحه
    try:
        page = int(event.args[0]) if event.args else 1
    except (ValueError, TypeError):
        page = 1

    if page < 1:
        page = 1

    total_pages = (
        len(commands) + HELP_PAGE_SIZE - 1
    ) // HELP_PAGE_SIZE

    if page > total_pages:
        page = total_pages

    start = (page - 1) * HELP_PAGE_SIZE
    end = start + HELP_PAGE_SIZE

    page_commands = commands[start:end]

    lines = [
        f"`!{cmd.name}`\n{cmd.description or 'بدون توضیح'}"
        for cmd in page_commands
    ]

    text = (
        f"📖 راهنما — صفحه {page}/{total_pages}\n\n"
        + "\n\n".join(lines)
    )

    if total_pages > 1:
        text += (
            "\n\n"
            f"📄 برای صفحه بعد: `!راهنما {page + 1}`"
            if page < total_pages
            else
            "\n\n"
            f"📄 برای صفحه قبل: `!راهنما {page - 1}`"
        )

    await event.reply(text)









@command(
    name="پلاگین آپدیت چک",
    permission="owner",
    chat_type="all",
    description="🔄 وجود پلاگین جدید یا نسخه‌ی جدید پلاگین‌ها را بررسی می‌کند.",
)
async def plugin_update_check(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    try:
        github = GitHubManager()

        updater = PluginUpdateManager(
            plugin_manager=self.plugin_manager,
            github=github,
        )

        result = await updater.check()

    except Exception as e:
        await event.reply(
            f"❌ بررسی پلاگین‌ها ناموفق بود.\n`{e}`"
        )
        return

    lines = []

    if result.new_plugins:
        lines.append("📦 پلاگین‌های جدید:")

        for plugin in result.new_plugins:
            lines.append(
                f"🔹 {plugin.name} — v{plugin.version}"
            )

    if result.updates:
        if lines:
            lines.append("")

        lines.append("🔄 بروزرسانی‌های موجود:")

        for plugin, local_version in result.updates:
            lines.append(
                f"🔹 {plugin.name} — "
                f"v{local_version} → v{plugin.version}"
            )

    if not lines:
        await event.reply(
            "✅ هیچ پلاگین جدید یا بروزرسانی‌ای پیدا نشد."
        )
        return

    await event.reply(
        "\n".join(lines)
    )






@command(
    name="گیتهاب چک",
    permission="owner",
    chat_type="all",
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
    permission="owner",
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
    permission="owner",
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









@command(
    name="لیست پلاگین ها",
    permission="owner",
    chat_type="all",
    description="📦 لیست پلاگین‌های نصب‌شده و نسخه‌ی آن‌ها را نشان می‌دهد.",
)
async def list_plugins(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    plugins = self.plugin_manager.get_all_plugins()

    if not plugins:
        await event.reply("📦 هیچ پلاگینی نصب نشده.")
        return

    lines = [
        f"🔹 **{plugin.name}** — version: {plugin.version}"
        for plugin in sorted(plugins, key=lambda p: p.name.lower())
    ]

    await event.reply(
        "📦 پلاگین‌های نصب‌شده:\n\n" +
        "\n".join(lines)
    )