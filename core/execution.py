"""
لایه‌ی «اجرای کامند».

handlerها فقط با یک `event` کار می‌کنند (event.reply، event.chat_id، ...).
اینکه این event از کجا آمده و پاسخش کجا برود، کار ExecutionEvent و Output است:

- event واقعی پیام، یا هیچ event (اجرای زمان‌بندی‌شده / برنامه‌نویسی‌شده)
- chat و sender دلخواه (مثل Remote Group)
- مقصد پاسخ: همان چت، چتی دیگر، owner، ثبت در لیست، هیچ‌جا، یا هر تابع دلخواه

کد handler همان کد معمولی می‌ماند و از هیچ‌کدام از این‌ها خبر ندارد.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from core.permissions import owner_ids


# =============================================================
# Output: مقصد event.reply / event.respond
# =============================================================

class Output:
    """مقصد پاسخ‌های handler. با factoryهای پایین ساخته می‌شود."""

    async def reply(self, ctx: "ExecutionEvent", *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def respond(self, ctx: "ExecutionEvent", *args: Any, **kwargs: Any) -> Any:
        return await self.reply(ctx, *args, **kwargs)

    @staticmethod
    def origin() -> "Output":
        """پاسخ روی event اصلی (پیش‌فرض)؛ بدون event اصلی → ارسال به chat_id."""
        return _Origin()

    @staticmethod
    def chat(chat_id: int) -> "Output":
        """پاسخ‌ها با client.send_message به یک چت مشخص می‌روند."""
        return _ToChat(chat_id)

    @staticmethod
    def owners() -> "Output":
        """پاسخ‌ها با client.send_message به PV همه‌ی ownerها می‌روند."""
        return _ToOwners()

    @staticmethod
    def capture() -> "CaptureOutput":
        """پاسخ‌ها ارسال نمی‌شوند؛ داخل .messages جمع می‌شوند."""
        return CaptureOutput()

    @staticmethod
    def silent() -> "Output":
        """پاسخ‌ها دور ریخته می‌شوند."""
        return _Silent()

    @staticmethod
    def custom(sender: Callable[..., Any]) -> "Output":
        """هر تابع دلخواه: sender(ctx, *args, **kwargs) (sync یا async)."""
        return _Custom(sender)


class _Origin(Output):
    async def reply(self, ctx, *args, **kwargs):
        if ctx.base is not None:
            return await ctx.base.reply(*args, **kwargs)
        return await self._fallback(ctx, *args, **kwargs)

    async def respond(self, ctx, *args, **kwargs):
        if ctx.base is not None:
            return await ctx.base.respond(*args, **kwargs)
        return await self._fallback(ctx, *args, **kwargs)

    @staticmethod
    async def _fallback(ctx, *args, **kwargs):
        if ctx.chat_id is not None:
            return await ctx.client.send_message(ctx.chat_id, *args, **kwargs)

        text = args[0] if args else kwargs.get("message", "")
        print(f"ℹ️ خروجی کامند (بدون مقصد): {text}")
        return None


class _ToChat(Output):
    def __init__(self, chat_id: int) -> None:
        self._chat_id = chat_id

    async def reply(self, ctx, *args, **kwargs):
        return await ctx.client.send_message(self._chat_id, *args, **kwargs)


class _ToOwners(Output):
    async def reply(self, ctx, *args, **kwargs):
        sent = None
        for owner_id in sorted(owner_ids()):
            sent = await ctx.client.send_message(owner_id, *args, **kwargs)
        return sent


class CaptureOutput(Output):
    def __init__(self) -> None:
        self.messages: list[str] = []

    @property
    def text(self) -> str:
        return "\n".join(self.messages)

    async def reply(self, ctx, *args, **kwargs):
        self.messages.append(str(args[0] if args else kwargs.get("message", "")))
        return None


class _Silent(Output):
    async def reply(self, ctx, *args, **kwargs):
        return None


class _Custom(Output):
    def __init__(self, sender: Callable[..., Any]) -> None:
        self._sender = sender

    async def reply(self, ctx, *args, **kwargs):
        result = self._sender(ctx, *args, **kwargs)

        if inspect.isawaitable(result):
            result = await result

        return result


# =============================================================
# ExecutionEvent: event‌ای که handler می‌بیند
# =============================================================

class ExecutionEvent:
    """
    یک «نمای» قابل‌تنظیم از event.

    - base=None  → کامند بدون event واقعی اجرا می‌شود (Scheduler، کد، webhook ...)
    - base=event → مقدارهایی که override نشده‌اند از event واقعی خوانده می‌شوند
    - هر ویژگی‌ای که اینجا تعریف نشده باشد به base واگذار می‌شود.

    override ها: chat_id، sender_id، is_group، args، raw_text، output.
    """

    def __init__(
        self,
        client: Any,
        *,
        base: Any = None,
        chat_id: int | None = None,
        sender_id: int | None = None,
        is_group: bool | None = None,
        args_text: str | None = None,
        raw_text: str | None = None,
        output: Output | None = None,
    ) -> None:
        self.client = client
        self.base = base
        self.output = output or Output.origin()

        self._chat_id = chat_id
        self._sender_id = sender_id
        self._is_group = is_group
        self._raw_text = raw_text
        self._chat_cache: Any = None

        if args_text is None:
            args_text = getattr(base, "args_text", "") or ""

        self.args_text: str = args_text
        self.args: list[str] = args_text.split() if args_text else []

    # ---------------------------------------------------------
    # ویژگی‌های ساده
    # ---------------------------------------------------------

    @property
    def _same_chat(self) -> bool:
        if self.base is None:
            return False

        return (
            self._chat_id is None
            or self._chat_id == getattr(self.base, "chat_id", None)
        )

    @property
    def chat_id(self) -> int | None:
        if self._chat_id is not None:
            return self._chat_id

        return getattr(self.base, "chat_id", None)

    @property
    def sender_id(self) -> int | None:
        if self._sender_id is not None:
            return self._sender_id

        return getattr(self.base, "sender_id", None)

    @property
    def is_group(self) -> bool:
        if self._is_group is not None:
            return self._is_group

        return bool(getattr(self.base, "is_group", False))

    @property
    def is_private(self) -> bool:
        if self._is_group is not None:
            return not self._is_group

        return bool(getattr(self.base, "is_private", False))

    @property
    def raw_text(self) -> str:
        if self._raw_text is not None:
            return self._raw_text

        return getattr(self.base, "raw_text", "") or ""

    @property
    def text(self) -> str:
        return self.raw_text

    @property
    def message(self) -> str:
        return self.raw_text

    @property
    def id(self) -> int | None:
        # id پیام فقط وقتی معنی دارد که هنوز در همان چتِ پیام اصلی باشیم.
        return getattr(self.base, "id", None) if self._same_chat else None

    @property
    def is_reply(self) -> bool:
        if not self._same_chat:
            return False

        return bool(getattr(self.base, "is_reply", False))

    # ---------------------------------------------------------
    # متدهای async
    # ---------------------------------------------------------

    async def get_chat(self) -> Any:
        if self._same_chat:
            return await self.base.get_chat()

        if self._chat_cache is None and self.chat_id is not None:
            self._chat_cache = await self.client.get_entity(self.chat_id)

        return self._chat_cache

    async def get_sender(self) -> Any:
        if (
            self._sender_id is not None
            and self._sender_id != getattr(self.base, "sender_id", None)
        ):
            return await self.client.get_entity(self._sender_id)

        if self.base is not None:
            return await self.base.get_sender()

        return None

    async def get_reply_message(self) -> Any:
        if self._same_chat:
            return await self.base.get_reply_message()

        return None

    async def reply(self, *args: Any, **kwargs: Any) -> Any:
        return await self.output.reply(self, *args, **kwargs)

    async def respond(self, *args: Any, **kwargs: Any) -> Any:
        return await self.output.respond(self, *args, **kwargs)

    async def delete(self) -> Any:
        # پیام واقعیِ کامند (مثلاً پیام حاوی API Key در PV) پاک می‌شود.
        if self.base is not None:
            return await self.base.delete()

        return None

    def __getattr__(self, name: str) -> Any:
        base = self.__dict__.get("base")

        if base is None or name.startswith("__"):
            raise AttributeError(name)

        return getattr(base, name)