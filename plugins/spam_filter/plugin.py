from . import handlers

from .context import SpamContextProvider
from .store import (
    SpamContextStore,
    SpamRuleStore,
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
    version = "1.4.5"

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

        self.rules = SpamRuleStore(
            self.db
        )

        self.context = SpamContextProvider(
            self.context_store,
            self.rules,
            self.client,
        )

        self.tracker = SpamTracker()
        self.telemetry = SpamTelemetry()
        self.admin_cache = AdminCache()

    async def on_load(self):
        await self.settings.create_table()
        await self.whitelist.create_table()
        await self.context_store.create_table()
        await self.rules.create_table()

    set_flood = handlers.set_flood
    set_max_repeat = handlers.set_max_repeat
    show_settings = handlers.show_settings

    add_whitelist = handlers.add_whitelist
    remove_whitelist = handlers.remove_whitelist
    list_whitelist = handlers.list_whitelist

    add_forbidden_rule = (
        handlers.add_forbidden_rule
    )

    add_allowed_rule = (
        handlers.add_allowed_rule
    )

    remove_forbidden_rule = (
        handlers.remove_forbidden_rule
    )

    remove_allowed_rule = (
        handlers.remove_allowed_rule
    )

    list_text_rules = (
        handlers.list_text_rules
    )

    on_member_change = (
        handlers.on_member_change
    )

    on_message = handlers.on_message

    on_spam_suspicious = (
        handlers.on_spam_suspicious
    )