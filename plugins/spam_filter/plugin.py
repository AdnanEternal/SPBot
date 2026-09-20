from . import handlers
from .store import SpamSettingsStore
from .tracker import AdminCache, SpamTracker

from core.base_plugin import BasePlugin


class SpamFilterPlugin(BasePlugin):
    """
    تشخیص اسپم با چند تا معیار ساده و قابل‌فهم (نه هوش مصنوعی/API
    بیرونی): فلاد پیام، پیام تکراریِ پشت‌سرهم، لینک زیاد تو یه پیام، و
    تکرار بیش‌ازحد یه کاراکتر. هرکدوم آستانه‌ی قابل‌تنظیم داره (به‌جز
    تکرار کاراکتر که ثابته)، ولی از همون اول با مقادیر پیش‌فرض معقول
    (تو store.py) کار می‌کنه.

    دقیقاً مثل content_filter، وقتی چیزی رو اسپم تشخیص بده پیام رو پاک
    می‌کنه و رو event_bus رویداد "violation" منتشر می‌کنه؛ اگه
    violation_manager نصب باشه خودش تصمیم می‌گیره مجازات کنه یا نه،
    وگرنه این پلاگین به‌تنهایی هم کار می‌کنه (فقط پاک‌سازی).
    """

    name = "Spam Filter"
    version = "1.2.4"

    def __init__(self, client, command_manager, db, event_bus):
        super().__init__(client, command_manager, db, event_bus)
        self.settings = SpamSettingsStore(self.db)
        self.tracker = SpamTracker()
        self.admin_cache = AdminCache()

    async def on_load(self):
        await self.settings.create_table()

    set_flood = handlers.set_flood
    set_max_links = handlers.set_max_links
    set_max_repeat = handlers.set_max_repeat
    show_settings = handlers.show_settings
    on_message = handlers.on_message
