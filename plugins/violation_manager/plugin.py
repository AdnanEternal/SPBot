from . import handlers
from .store import GroupSettingsStore, ViolationStore

from core.base_plugin import BasePlugin


class ViolationManagerPlugin(BasePlugin):
    """
    ثبت تخلف کاربران به‌ازای هر گروه، تنظیمات سقف تخلف/نوع مجازات هر
    گروه، و اجرای خودِ مجازات (میوت یا بن).

    پلاگین‌های دیگه (مثل content_filter) یه تخلف رو با emit کردن رویداد
    "violation" رو event_bus گزارش می‌کنن؛ این پلاگین هیچ وابستگی
    مستقیمی بهشون نداره — اگه content_filter نصب نباشه، این پلاگین بدون
    مشکل کار می‌کنه، فقط دیگه تخلفی از اون مسیر گزارش نمی‌شه.
    """

    name = "Violation Manager"
    version = "1.6.3"

    def __init__(self, client, command_manager, db, event_bus):
        super().__init__(client, command_manager, db, event_bus)
        self.violations = ViolationStore(self.db)
        self.settings = GroupSettingsStore(self.db)

    async def on_load(self):
        await self.violations.create_table()
        await self.settings.create_table()

    list_violators = handlers.list_violators
    set_max_violations = handlers.set_max_violations
    set_punishment_mute = handlers.set_punishment_mute
    set_punishment_ban = handlers.set_punishment_ban
    my_record = handlers.my_record
    mute_command = handlers.mute_command
    unmute_command = handlers.unmute_command
    on_reply_shortcut = handlers.on_reply_shortcut
    on_violation = handlers.on_violation
    clear_record = handlers.clear_record