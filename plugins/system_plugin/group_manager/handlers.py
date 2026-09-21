from typing import TYPE_CHECKING

from core.decorators import (
    on_command_invocation,
)


if TYPE_CHECKING:
    from ..plugin import SystemPlugin


@on_command_invocation(
    priority=-100,
)
async def remote_group_invocation(
    self: "SystemPlugin",
    invocation,
) -> None:
    """
    Hook مدیریت Remote Group Command.

    چون priority منفی است، قبل از Hookهای عادی اجرا می‌شود.
    """

    if not hasattr(
        self,
        "group_manager",
    ):
        return

    await self.group_manager.handle_invocation(
        invocation
    )