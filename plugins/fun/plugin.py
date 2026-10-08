from core.base_plugin import BasePlugin

from . import handlers


class FunPlugin(BasePlugin):
    name = "Fun"
    version = "1.0.1"

    DEBUG_LOGGING = 0

    def debug(
        self,
        category: str,
        message: str,
    ) -> None:
        if not self.DEBUG_LOGGING:
            return

        print(
            f"[Fun][{category}] {message}",
            flush=True,
        )

    cat = handlers.cat
    on_cat_trigger = handlers.on_cat_trigger