from core.base_plugin import BasePlugin

from . import handlers


class MessageManagerPlugin(BasePlugin):

    name = "Message manager"

    version = "1.3.3"

    clear_message = handlers.clear_messages
    meow_trigger = handlers.meow_trigger