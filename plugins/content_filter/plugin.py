from . import handlers

from .store import (
    ContentFilterSettingsStore,
    WordFilterStore,
)

from core.base_plugin import BasePlugin


class ContentFilterPlugin(BasePlugin):
    """
    این فایل فقط ورودیِ پلاگینه: کلاس رو تعریف می‌کنه و هندلرهایی که
    واقعاً توی handlers.py نوشته و دکوریت شدن رو بهش وصل می‌کنه.

    هیچ منطقی این‌جا نوشته نمی‌شه؛ پلاگین‌منیجر هم فقط همین فایل
    (plugins/<name>/plugin.py) رو می‌شناسه و import می‌کنه.
    """

    name = "Content Filter"
    version = "2.6.0"

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

    async def on_load(self):
        await self.words.create_table()
        await self.settings.create_table()

    add_word = handlers.add_word

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

    contribute_spam_signals = (
        handlers.contribute_spam_signals
    )