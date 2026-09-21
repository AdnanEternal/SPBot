from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from core.command_manager import Command


EventHandler = Callable[
    [Any],
    Awaitable[Any],
]


@dataclass
class CommandInvocation:
    """
    نمایش عمومی یک تلاش برای اجرای Command.

    Invocation مستقل از منبع اجراست.
    """

    command: "Command"

    # Event اصلی که Invocation از آن ساخته شده.
    # برای Authorization و حفظ هویت منبع مهم است.
    original_event: Any

    args_text: str = ""

    args: list[str] = field(
        default_factory=list
    )

    source: str = "message"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # Event فعلی که Handler دریافت می‌کند.
    event: Any = None

    # Handler فعلی.
    handler: EventHandler | None = None

    # None = هنوز Authorization مشخص نشده
    # True = مجاز
    # False = غیرمجاز
    access_granted: bool | None = None

    blocked: bool = False
    handled: bool = False
    executed: bool = False

    stop_hooks: bool = False

    block_reason: str | None = None

    # آیا Command توسط سیستم مصرف شده؟
    consumed: bool = False

    def __post_init__(self) -> None:
        if self.event is None:
            self.event = self.original_event

        if self.handler is None:
            self.handler = self.command.handler

    @property
    def command_name(self) -> str:
        return self.command.name

    @property
    def plugin(self) -> object | None:
        return self.command.plugin

    @property
    def is_group(self) -> bool:
        return bool(
            getattr(
                self.event,
                "is_group",
                False,
            )
        )

    @property
    def is_private(self) -> bool:
        return bool(
            getattr(
                self.event,
                "is_private",
                False,
            )
        )

    def replace_handler(
        self,
        handler: EventHandler,
    ) -> None:
        """
        Handler فقط برای همین Invocation عوض می‌شود.
        """

        if not callable(handler):
            raise TypeError(
                "CommandInvocation handler "
                "must be callable."
            )

        self.handler = handler

    def replace_event(
        self,
        event: Any,
    ) -> None:
        """
        Event/Context فعلی Handler را عوض می‌کند.

        original_event دست‌نخورده باقی می‌ماند.
        """

        if event is None:
            raise ValueError(
                "CommandInvocation event "
                "cannot be None."
            )

        self.event = event

    def set_args(
        self,
        args_text: str,
    ) -> None:
        """
        آرگومان‌های این Invocation را تغییر می‌دهد.
        """

        self.args_text = (
            args_text or ""
        ).strip()

        self.args = (
            self.args_text.split()
            if self.args_text
            else []
        )

        self.event.args_text = (
            self.args_text
        )

        self.event.args = list(
            self.args
        )

    def grant_access(self) -> None:
        """
        Authorization را موفق علامت می‌زند.
        """

        self.access_granted = True

    def deny_access(
        self,
        reason: str | None = None,
    ) -> None:
        self.access_granted = False
        self.stop_hooks = True

        if reason:
            self.block_reason = reason

    def block(
        self,
        reason: str | None = None,
    ) -> None:
        self.blocked = True
        self.stop_hooks = True
        self.consumed = True

        if reason:
            self.block_reason = reason

    def mark_handled(self) -> None:
        self.handled = True
        self.stop_hooks = True
        self.consumed = True