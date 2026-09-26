from . import handlers

from .context import SpamContextProvider
from .store import (
    SpamContextStore,
    SpamSettingsStore,
    SpamWhitelistStore,
)
from .telemetry import SpamTelemetry
from .tracker import (
    AdminCache,
    SpamTracker,
)

from core.base_plugin import BasePlugin


class SpamFilterPlugin(BasePlugin):
    name = "Spam Filter"

    version = "1.4.1"

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

        self.settings = SpamSettingsStore(
            self.db
        )

        self.whitelist = SpamWhitelistStore(
            self.db
        )

        self.context_store = SpamContextStore(
            self.db
        )

        self.context = SpamContextProvider(
            self.context_store,
            self.client,
        )

        self.tracker = SpamTracker()
        self.telemetry = SpamTelemetry()

        self.admin_cache = AdminCache()

    async def on_load(self):
        await self.settings.create_table()
        await self.whitelist.create_table()
        await self.context_store.create_table()

    set_flood = handlers.set_flood
    set_max_links = handlers.set_max_links
    set_max_repeat = handlers.set_max_repeat
    show_settings = handlers.show_settings

    add_whitelist = handlers.add_whitelist
    remove_whitelist = handlers.remove_whitelist
    list_whitelist = handlers.list_whitelist

    on_member_change = handlers.on_member_change
    on_message = handlers.on_message

    on_spam_suspicious = (
        handlers.on_spam_suspicious
    )