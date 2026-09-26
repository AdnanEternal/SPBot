from . import handlers
from .store import SpamSettingsStore, SpamWhitelistStore
from .tracker import AdminCache, SpamTracker

from core.base_plugin import BasePlugin


class SpamFilterPlugin(BasePlugin):
    name = "Spam Filter"
    version = "1.3.0"

    def __init__(self, client, command_manager, db, event_bus):
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

        self.tracker = SpamTracker()
        self.admin_cache = AdminCache()

    async def on_load(self):
        await self.settings.create_table()
        await self.whitelist.create_table()

    set_flood = handlers.set_flood
    set_max_links = handlers.set_max_links
    set_max_repeat = handlers.set_max_repeat
    show_settings = handlers.show_settings

    add_whitelist = handlers.add_whitelist
    remove_whitelist = handlers.remove_whitelist
    list_whitelist = handlers.list_whitelist

    on_message = handlers.on_message