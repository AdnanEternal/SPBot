
from core.base_plugin import BasePlugin

from . import handlers


class FunPlugin(BasePlugin):
    name = "Fun"
    version = "2.1.0"

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

    # Commands
    cat = handlers.cat

    # Message triggers
    on_cat_trigger = handlers.on_cat_trigger

    # AI response composition
    prepare_response_composition = (
        handlers.prepare_response_composition
    )

    finalize_response_composition = (
        handlers.finalize_response_composition
    )

    fail_response_composition = (
        handlers.fail_response_composition
    )

    finalize_without_ai = (
        handlers.finalize_without_ai
    )