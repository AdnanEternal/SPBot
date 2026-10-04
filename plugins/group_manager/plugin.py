from . import handlers

from core.base_plugin import BasePlugin


class GroupManagerPlugin(BasePlugin):
    name = "Group Manager"
    version = "1.0.0"

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

    group_stats = handlers.group_stats
    on_message = handlers.on_message