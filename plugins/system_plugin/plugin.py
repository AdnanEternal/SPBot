from . import handlers

import asyncio

from core.base_plugin import BasePlugin


class SystemPlugin(BasePlugin):
    """
    پلاگین سیستمی: خونه‌ی کامندها و قابلیت‌های مدیریتیِ خودِ ربات (نه یه
    قابلیت کاربرمحور مثل فیلتر محتوا). الان فقط !راهنما رو داره، ولی
    قراره بعداً کارهای دیگه‌ای مثل فعال/غیرفعال کردن سایر پلاگین‌ها هم
    بهش اضافه بشه؛ برای همین به‌جای handlers.py تک‌فایلی، بعداً می‌تونی
    هر دسته‌کار رو تو فایل جدا بنویسی (مثلاً plugins_control.py) و همون‌جا
    به کلاس وصلش کنی، دقیقاً مثل show_help پایین.

    از نگاه core این پلاگین هیچ فرقی با بقیه‌ی پلاگین‌ها نداره؛ فقط از
    قابلیت‌های عمومیِ خودِ core (مثل command_manager.get_all_commands())
    استفاده می‌کنه. یعنی اگه غیرفعال یا حذف بشه، بقیه‌ی ربات دقیقاً مثل
    قبل کار می‌کنه.
    """

    def __init__(
        self,
        client,
        command_manager,
        db,
        event_bus,
    ):
        super().__init__(
            client,
            command_manager,
            db,
            event_bus,
        )

        self.runtime_update_lock = asyncio.Lock()

    name = "System"
    version = "2.9.4"

    show_help = handlers.show_help
    github_check = handlers.github_check
    database_backup = handlers.database_backup
    database_restore = handlers.database_restore
    list_plugins = handlers.list_plugins
    plugin_update_check = handlers.plugin_update_check
    plugin_install = handlers.plugin_install
    plugin_update = handlers.plugin_update