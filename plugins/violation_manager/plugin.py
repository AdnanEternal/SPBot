from . import handlers
from .store import ViolationStore
from core.base_plugin import BasePlugin


class ViolationManagerPlugin(BasePlugin):

    name = "Violation Manager"
    version = "0.9.0"

    def __init__(self, client, command_manager, db):
        super().__init__(client, command_manager, db)
        self.violations = ViolationStore(self.db)
    async def on_load(self):
        await self.violations.create_table()

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass


    list_violators = handlers.list_violators