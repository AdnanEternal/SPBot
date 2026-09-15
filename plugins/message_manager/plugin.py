from core.base_plugin import BasePlugin

from . import handlers


class MessageManagerPlugin(BasePlugin):

    name = "Message manager"

    version = '1.0.0'

    clear_message = handlers.clear_messages