from core.base_plugin import BasePlugin

from . import handlers


class FunPlugin(BasePlugin):
    name = "Fun"
    version = "0.1.0"

    cat = handlers.cat