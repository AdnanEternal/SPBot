from . import handlers

from .store import (
    ContentFilterSettingsStore,
    ContentFilterViolationStore,
    WordFilterStore,
)

from core.base_plugin import BasePlugin


class ContentFilterPlugin(BasePlugin):
    """
    پلاگین فیلتر محتوای گروه.

    مسئولیت‌های این پلاگین:

    - مدیریت لیست کلمات فیلترشده
    - فیلتر کردن پیام
    - ثبت سابقه‌ی اختصاصی Content Filter
    - درخواست مجازات بعد از عبور از سقف تخلف

    Content Filter هیچ وابستگی‌ای به Spam Filter ندارد.
    """

    name = "Content Filter"
    version = "2.6.1"

    # حداکثر تعداد تخلف قبل از درخواست مجازات.
    #
    # 3 تخلف مجاز است.
    # تخلف چهارم -> درخواست مجازات
    MAX_VIOLATIONS = 3

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

        self.words = WordFilterStore(
            self.db
        )

        self.settings = (
            ContentFilterSettingsStore(
                self.db
            )
        )

        self.violations = (
            ContentFilterViolationStore(
                self.db
            )
        )

    async def on_load(self):
        await self.words.create_table()
        await self.settings.create_table()
        await self.violations.create_table()

    add_word = (
        handlers.add_word
    )

    remove_word = (
        handlers.remove_word
    )

    list_words = (
        handlers.list_words
    )

    set_admin_filter_permission = (
        handlers.set_admin_filter_permission
    )

    on_message = (
        handlers.on_message
    )