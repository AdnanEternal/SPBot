from core.base_plugin import BasePlugin

from . import handlers


class FunPlugin(BasePlugin):
    name = "Fun"
    version = "2.2.0"

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
    dog = handlers.dog

    # Message triggers
    on_media_trigger = handlers.on_media_trigger

    # AI response ownership
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