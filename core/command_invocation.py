from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from core.execution import ExecutionEvent, Output

if TYPE_CHECKING:
    from core.command_manager import Command


EventHandler = Callable[
    [Any],
    Awaitable[Any],
]

# around(call_next, event): call_next(event=None) → handler بعدی/اصلی را اجرا می‌کند.
AroundHandler = Callable[
    [Callable[..., Awaitable[Any]], Any],
    Awaitable[Any] | Any,
]


@dataclass
class CommandInvocation:
    """
    نمایش عمومی یک تلاش برای اجرای Command.

    این کلاس هیچ اطلاعی از Group Manager، AI Gateway یا هر Plugin
    دیگری ندارد.

    Invocation می‌تواند از هر منبعی ساخته شود:
    - پیام عادی
    - Remote Command
    - Scheduler
    - پنل مدیریتی
    - سیستم داخلی دیگر

    Hookها (@on_command_invocation) هر چیزی را می‌توانند عوض کنند:
    آرگومان‌ها، event، مقصد پاسخ، سطح دسترسی، یا کل handler.
    """

    command: "Command"
    original_event: Any

    args_text: str = ""
    args: list[str] = field(
        default_factory=list
    )

    source: str = "message"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # Event فعلی که Handler در نهایت دریافت می‌کند.
    event: Any = None

    # Handler فعلی.
    handler: EventHandler | None = None

    # None = هنوز Authorization مشخص نشده
    # True = مجاز
    # False = غیرمجاز
    access_granted: bool | None = None

    # Hook می‌تواند Command را کاملاً متوقف کند.
    blocked: bool = False

    # Hook می‌تواند خودش Command را مدیریت کند.
    handled: bool = False

    # آیا Handler واقعاً اجرا شده؟
    executed: bool = False

    # متوقف شدن زنجیره Hookها.
    stop_hooks: bool = False

    block_reason: str | None = None

    # آیا پیام واقعاً توسط سیستم Command مصرف شده؟
    consumed: bool = False

    # client ربات (برای redirect_output و ساخت eventهای جدید)
    client: Any = None

    # سطح دسترسیِ اعطاشده: "everyone" | "admin" | "owner"
    # (کامندهایی که سطحشان ≤ این مقدار است، بدون بررسی کاربر مجاز می‌شوند.)
    granted_level: str | None = None

    # مقدار برگشتیِ handler (بعد از اجرا)
    result: Any = None

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
        Handler ثبت‌شده‌ی اصلی Command تغییر نمی‌کند.
        """

        if not callable(handler):
            raise TypeError(
                "CommandInvocation handler must be callable."
            )

        self.handler = handler

    def wrap_handler(
        self,
        around: AroundHandler,
    ) -> None:
        """
        دور handler فعلی یک لایه می‌پیچد (قبل/بعد از اجرا، try/except، تایمر، ...).

            async def around(call_next, event):
                await event.reply("شروع شد")
                result = await call_next()          # یا call_next(event_دیگر)
                return result

            invocation.wrap_handler(around)
        """

        if not callable(around):
            raise TypeError(
                "CommandInvocation wrapper must be callable."
            )

        inner = self.handler

        async def wrapped(event: Any) -> Any:
            async def call_next(new_event: Any = None) -> Any:
                result = inner(
                    event if new_event is None else new_event
                )

                if inspect.isawaitable(result):
                    result = await result

                return result

            result = around(call_next, event)

            if inspect.isawaitable(result):
                result = await result

            return result

        self.handler = wrapped

    def replace_event(
        self,
        event: Any,
    ) -> None:
        """
        Contextی که Handler دریافت می‌کند را عوض می‌کند.

        original_event عمداً دست‌نخورده باقی می‌ماند تا
        Authorization نتواند با عوض کردن Event دور زده شود.
        """

        if event is None:
            raise ValueError(
                "CommandInvocation event cannot be None."
            )

        self.event = event

    def redirect_output(
        self,
        output: Output,
    ) -> None:
        """
        هر event.reply / event.respond داخل handler به `output` می‌رود؛
        کد handler دست نمی‌خورد.

            invocation.redirect_output(Output.owners())
            invocation.redirect_output(Output.chat(group_id))
            invocation.redirect_output(Output.custom(my_sender))
        """

        self.replace_event(
            ExecutionEvent(
                self.client,
                base=self.event,
                output=output,
            )
        )

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
        Authorization را به‌عنوان انجام‌شده و موفق علامت می‌زند.
        """

        self.access_granted = True

    def grant_level(
        self,
        level: str,
    ) -> None:
        """
        این Invocation با سطح دسترسی `level` اجرا شود
        ("everyone" | "admin" | "owner").

        برخلاف grant_access() که کل Authorization را رد می‌کند،
        اینجا فقط کامندهایی مجاز می‌شوند که سطحشان ≤ level باشد؛
        بقیه همچنان بررسی عادیِ کاربر را طی می‌کنند.
        """

        self.granted_level = level

    def deny_access(
        self,
        reason: str | None = None,
    ) -> None:
        """
        دسترسی این Invocation رد شده است.

        رد شدن Permission به‌تنهایی به معنی مصرف شدن پیام نیست؛
        بنابراین پیام می‌تواند به Handlerهای دیگر برسد.
        """

        self.access_granted = False
        self.stop_hooks = True

        if reason:
            self.block_reason = reason

    def block(
        self,
        reason: str | None = None,
    ) -> None:
        """
        اجرای Command را متوقف می‌کند.

        این Invocation همچنان مصرف‌شده حساب می‌شود و به Handler
        اصلی نمی‌رسد.
        """

        self.blocked = True
        self.stop_hooks = True
        self.consumed = True

        if reason:
            self.block_reason = reason

    def mark_handled(self) -> None:
        """
        Hook خودش Invocation را مدیریت کرده است.
        Handler اصلی دیگر اجرا نمی‌شود.
        """

        self.handled = True
        self.stop_hooks = True
        self.consumed = True