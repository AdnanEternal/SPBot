from typing import TYPE_CHECKING

from splusthon import events, utils
from splusthon.tl import functions, types

from core.decorators import command, on_event
from core.permissions import (
    get_admins,
    is_chat_admin,
    is_owner,
)

from .backup.backup import (
    AUTO_RESTORE_DATABASE_ON_STARTUP,
    DatabaseBackupManager,
)
from .github_manager.manager import GitHubManager
from .plugin_updater import PluginUpdateManager

if TYPE_CHECKING:
    from .plugin import SystemPlugin

HELP_PAGE_SIZE = 6



ADMIN_LIST_MAX_CHARS = 1200


def _build_admin_block(
    index: int,
    admin,
) -> str:

    entity = admin.entity

    first_name = (
        getattr(
            entity,
            "first_name",
            None,
        )
        or ""
    ).strip()

    last_name = (
        getattr(
            entity,
            "last_name",
            None,
        )
        or ""
    ).strip()

    username = (
        getattr(
            entity,
            "username",
            None,
        )
        or None
    )

    full_name = (
        f"{first_name} {last_name}"
    ).strip()

    if not full_name:
        full_name = str(
            admin.user_id
        )

    return "\n".join([
        "----------------------------------",
        f"👤 ادمین شماره {index}:",
        f"📝 نام: {full_name}",
        f"🔗 نام کاربری: "
        f"{('@' + username) if username else 'ندارد'}",
        f"🏷️ نقش: {admin.title}",
        "🔎 [مشاهده نمایه]",
    ])


async def _send_admin_list(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
    admins,
) -> None:

    if not admins:
        await event.reply(
            "ℹ️ هیچ ادمینی پیدا نشد."
        )
        return

    header = "\n".join([
        "👑 ادمین‌های این گروه:",
        f"👥 تعداد: {len(admins)} نفر",
    ])

    # هر آیتم شامل متن + ادمین خودش است.
    admin_items = [
        (
            _build_admin_block(
                index,
                admin,
            ),
            admin,
        )
        for index, admin in enumerate(
            admins,
            start=1,
        )
    ]

    messages = []

    current_items = []
    current_length = (
        len(header) + 2
    )

    for block, admin in admin_items:

        separator_length = (
            2
            if current_items
            else 0
        )

        required_length = (
            separator_length
            + len(block)
        )

        # اگر این block داخل پیام جا نمی‌شود،
        # پیام فعلی را می‌بندیم.
        if (
            current_items
            and
            current_length
            + required_length
            > ADMIN_LIST_MAX_CHARS
        ):
            messages.append(
                current_items
            )

            current_items = []

            # بعد از پیام اول، header دیگر وجود ندارد.
            current_length = 0

            separator_length = 0
            required_length = len(block)

        current_items.append(
            (block, admin)
        )

        current_length += required_length

    if current_items:
        messages.append(
            current_items
        )

    # -------------------------------------------------
    # ارسال
    # -------------------------------------------------

    for message_index, items in enumerate(
        messages,
    ):

        parts = []

        if message_index == 0:
            parts.append(header)

        for block, _admin in items:
            parts.append(block)

        text = "\n\n".join(parts)

        entity_positions = []

        search_from = 0

        for _block, admin in items:

            label = "[مشاهده نمایه]"

            position = text.find(
                label,
                search_from,
            )

            if position == -1:
                continue

            input_user = utils.get_input_user(
                admin.entity
            )

            entity_positions.append(
                types.InputMessageEntityMentionName(
                    offset=_utf16_length(
                        text[:position]
                    ),
                    length=_utf16_length(
                        label
                    ),
                    user_id=input_user,
                )
            )

            search_from = (
                position
                + len(label)
            )

        await event.reply(
            text,
            formatting_entities=entity_positions,
            parse_mode=None,
        )


def _is_admin_list_shortcut(text: str) -> bool:
    text = (text or "").strip()

    if not text:
        return False

    parts = text.split()

    # لیست ادمین / ادمین لیست
    if len(parts) == 2:
        if set(parts) == {"لیست", "ادمین"}:
            return True

        # لیست ادمینها / ادمینها لیست
        if set(parts) == {"لیست", "ادمینها"}:
            return True

        return False

    # لیست ادمین ها / ادمین ها لیست
    if len(parts) == 3:
        return (
            "لیست" in parts
            and "ادمین" in parts
            and "ها" in parts
        )

    return False


def _utf16_length(text: str) -> int:
    return len(
        text.encode("utf-16-le")
    ) // 2



@command(
    name="راهنما",
    permission="everyone",
    chat_type="all",
    description="❓لیست کامندهای قابل استفاده را نشان می‌دهد.",
    native_name="help",
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

    else:
        allowed_permissions = {"everyone"}

    commands = [
        cmd
        for cmd in self.command_manager.get_all_commands()
        if cmd.permission in allowed_permissions
    ]

    commands.sort(
        key=lambda cmd:
            self.command_manager.get_display_name(
                cmd
            )
    )

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
        (
            self.command_usage(
                cmd,
                event=event
            )
            + "\n"
            + (
                cmd.description
                or "بدون توضیح"
            )
        )
        for cmd in page_commands
    ]

    text = (
        f"📖 راهنما — صفحه {page}/{total_pages}\n\n"
        + "\n\n".join(lines)
    )

    controls = self.ui.pagination(
        command_or_name=event.command,
        current=page,
        total=total_pages,
    )

    await self.ui.reply(
        event,
        text,
        controls=controls,
    )



@command(
    name="لیست ادمین ها",
    permission="admin",
    chat_type="group",
    description="لیست ادمین‌های گروه را نشان می‌دهد.",
    native_name="admins",
)
async def list_admins(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:

    try:
        chat = await event.get_chat()

        admins = await get_admins(
            self.client,
            chat,
            force_refresh=True,
        )

    except Exception:
        print(
            "❌ خطا در دریافت لیست ادمین‌های گروه:"
        )
        import traceback
        traceback.print_exc()

        await event.reply(
            "❌ دریافت لیست ادمین‌ها ناموفق بود."
        )
        return

    if admins is None:
        await event.reply(
            "❌ امکان دریافت ادمین‌های این گروه وجود ندارد."
        )
        return

    await _send_admin_list(
        self,
        event,
        admins,
    )



@command(
    name="پلاگین آپدیت چک",
    permission="owner",
    chat_type="all",
    description="🔄 وجود پلاگین جدید یا نسخه‌ی جدید پلاگین‌ها را بررسی می‌کند.",
    native_name="plugin_check",
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
    native_name="github_check",
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

async def on_startup(
    self: "SystemPlugin",
) -> None:

    if not AUTO_RESTORE_DATABASE_ON_STARTUP:
        print(
            "ℹ️ بازیابی خودکار دیتابیس هنگام startup خاموش است."
        )
        return

    print(
        "♻️ بازیابی خودکار دیتابیس هنگام startup..."
    )

    github = GitHubManager()

    backup = DatabaseBackupManager(
        db=self.db,
        github=github,
    )

    await backup.restore_backup()

    print(
        "✅ بازیابی خودکار دیتابیس هنگام startup انجام شد."
    )

@command(
    name="دیتابیس بکاپ",
    permission="owner",
    chat_type="all",
    description="💾 یک نسخه از دیتابیس را در GitHub ذخیره می‌کند.",
    native_name="database_backup",
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
    native_name="database_restore",
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
        for plugin in self.plugin_manager.get_all_plugins():
            try:
                await plugin.on_load()
            except Exception as e:
                print(
                    f"❌ خطا در بازسازی دیتابیس پلاگین "
                    f"'{plugin.name}': {e}"
                )

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
    native_name="plugins",
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



@command(
    name="پلاگین دریافت",
    permission="owner",
    chat_type="all",
    description="📥 یک پلاگین را از GitHub دریافت و در runtime فعال می‌کند.",
    native_name="plugin_install",
)
async def plugin_install(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    if not event.args:

        await event.reply(
            "❌ شناسه‌ی پلاگین را وارد کن.\n"
            "مثال:\n"
            + self.command_usage(
                event.command,
                "message_manager",
                event=event,
            )
        )
        
        return

    plugin_id = event.args[0]

    try:
        github = GitHubManager()

        updater = PluginUpdateManager(
            plugin_manager=self.plugin_manager,
            github=github,
        )

        async with self.runtime_update_lock:
            plugin = await updater.install(
                plugin_id
            )

    except Exception as e:
        await event.reply(
            f"❌ دریافت پلاگین ناموفق بود.\n`{e}`"
        )
        return

    await event.reply(
        f"✅ پلاگین «{plugin.name}» "
        f"v{plugin.version} "
        f"در runtime نصب و فعال شد."
    )


@command(
    name="پلاگین آپدیت",
    permission="owner",
    chat_type="all",
    description="🔄 یک پلاگین را در runtime به‌روزرسانی می‌کند.",
    native_name="plugin_update",
)
async def plugin_update(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:
    if not event.args:
        await event.reply(
            "❌ شناسه‌ی پلاگین را وارد کن.\n"
            "مثال:\n"
            + self.command_usage(
                event.command,
                "violation_manager",
                event=event,
            )
        )
        return

    plugin_id = event.args[0]

    try:
        github = GitHubManager()

        updater = PluginUpdateManager(
            plugin_manager=self.plugin_manager,
            github=github,
        )

        async with self.runtime_update_lock:
            plugin = await updater.update(
                plugin_id
            )

    except Exception as e:
        await event.reply(
            f"❌ بروزرسانی پلاگین ناموفق بود.\n`{e}`"
        )
        return

    await event.reply(
        f"✅ پلاگین «{plugin.name}» "
        f"به v{plugin.version} "
        f"در runtime بروزرسانی شد."
    )


@on_event(events.NewMessage(incoming=True))
async def on_message(
    self: "SystemPlugin",
    event: events.NewMessage.Event,
) -> None:

    if not event.is_group:
        return


    text = event.raw_text or ""

    if not _is_admin_list_shortcut(text):
        return
    
    
    chat = await event.get_chat()

    try:
        admins = await get_admins(
            self.client,
            chat,
            force_refresh=True,
        )

    except Exception:
        print(
            "❌ خطا در دریافت ادمین‌ها برای shortcut:"
        )
        import traceback
        traceback.print_exc()
        return


    if admins is None:
        print("get_admins returned None")
        return

    if not any(
        admin.user_id == event.sender_id
        for admin in admins
    ):
        return

    await _send_admin_list(
        self,
        event,
        admins,
    )