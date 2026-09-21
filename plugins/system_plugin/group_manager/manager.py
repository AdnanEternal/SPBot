from __future__ import annotations

import re
from typing import Any


_GROUP_TARGET_PATTERN = re.compile(
    r"(?:^|\s)group_target=(-?\d+)\s*$",
    re.IGNORECASE,
)

_GROUP_TARGET_FLAG_PATTERN = re.compile(
    r"(?:^|\s)--group-target\s+(-?\d+)\s*$",
    re.IGNORECASE,
)


class RemoteGroupEvent:
    """
    Eventی که Handler مقصد دریافت می‌کند.

    Context این Event مربوط به گروه هدف است،
    ولی پاسخ‌ها به Event اصلی Owner در PV برمی‌گردند.

    این Event هرگز مستقیماً وارد SPlusthon Event Dispatcher
    نمی‌شود؛ فقط به Handler همان Command داده می‌شود.
    """

    def __init__(
        self,
        client,
        original_event: Any,
        group_id: int,
        command_name: str,
        args_text: str,
    ) -> None:
        self._client = client
        self._original_event = original_event

        # Context گروه هدف
        self.chat_id = group_id
        self.is_group = True
        self.is_private = False

        # هویت همچنان Owner اصلی است.
        self.sender_id = (
            original_event.sender_id
        )

        # Command بدون group_target
        self.command_name = command_name

        self.args_text = (
            args_text or ""
        ).strip()

        self.args = (
            self.args_text.split()
            if self.args_text
            else []
        )

        self.raw_text = (
            f"!{command_name}"
            + (
                f" {self.args_text}"
                if self.args_text
                else ""
            )
        )

        self.message = self.raw_text
        self.text = self.raw_text

        self.is_reply = False

        self._chat = None

    async def get_chat(self):
        """
        Chat مربوط به گروه هدف را می‌دهد.
        """

        if self._chat is None:
            self._chat = await self._client.get_entity(
                self.chat_id
            )

        return self._chat

    async def get_sender(self):
        """
        Sender همان Ownerی است که Command را از PV فرستاده.
        """

        return await self._original_event.get_sender()

    async def get_reply_message(self):
        """
        Remote Command فعلاً Reply گروهی ندارد.

        چون Command از PV آمده، Reply موجود در PV نباید
        به‌عنوان Reply گروه هدف تفسیر شود.
        """

        return None

    async def reply(
        self,
        *args,
        **kwargs,
    ):
        """
        پاسخ Handler را به PV اصلی Owner می‌فرستد.
        """

        return await self._original_event.reply(
            *args,
            **kwargs,
        )

    async def respond(
        self,
        *args,
        **kwargs,
    ):
        """
        پاسخ Handler را به PV اصلی Owner می‌فرستد.
        """

        return await self._original_event.respond(
            *args,
            **kwargs,
        )

    async def delete(self):
        """
        اگر Handler بخواهد Command را حذف کند،
        پیام اصلی PV حذف می‌شود.
        """

        return await self._original_event.delete()

    def __getattr__(
        self,
        name: str,
    ):
        """
        سایر ویژگی‌های Event اصلی را در اختیار Handler می‌گذارد.
        """

        return getattr(
            self._original_event,
            name,
        )


class GroupManager:
    """
    اجرای Remote Command برای یک گروه مشخص.

    این کلاس فقط در System Plugin زندگی می‌کند و
    هیچ Plugin دیگری را نمی‌شناسد.
    """

    def __init__(
        self,
        client,
    ) -> None:
        self.client = client

    @staticmethod
    def extract_group_target(
        args_text: str,
    ) -> tuple[str, int | None, bool]:
        """
        group_target را از انتهای آرگومان‌ها جدا می‌کند.

        پشتیبانی می‌شود:

            group_target=123456789

        و:

            --group-target 123456789

        خروجی:

            (clean_args, group_id, found)

        اگر marker وجود نداشته باشد:

            (..., None, False)
        """

        text = (
            args_text or ""
        ).strip()

        if not text:
            return "", None, False

        match = _GROUP_TARGET_PATTERN.search(
            text
        )

        if match:
            group_id = int(
                match.group(1)
            )

            clean = text[
                :match.start()
            ].strip()

            return (
                clean,
                group_id,
                True,
            )

        match = _GROUP_TARGET_FLAG_PATTERN.search(
            text
        )

        if match:
            group_id = int(
                match.group(1)
            )

            clean = text[
                :match.start()
            ].strip()

            return (
                clean,
                group_id,
                True,
            )

        return (
            text,
            None,
            False,
        )

    async def handle_invocation(
        self,
        invocation,
    ) -> None:
        """
        اگر Invocation یک Remote Group Command باشد،
        آن را به Context گروه هدف تبدیل می‌کند.

        در غیر این صورت هیچ تغییری ایجاد نمی‌کند.
        """

        event = (
            invocation.original_event
        )

        # فقط از PV
        if not getattr(
            event,
            "is_private",
            False,
        ):
            return

        # فقط Owner
        from core.permissions import is_owner

        if not is_owner(
            event.sender_id
        ):
            return

        clean_args, group_id, found = (
            self.extract_group_target(
                invocation.args_text
            )
        )

        # group_target وجود ندارد.
        # این Command یک اجرای عادی PV است.
        if not found:
            return

        # Commandهای private-only را نمی‌توان
        # روی Group Context اجرا کرد.
        if (
            invocation.command.chat_type
            == "private"
        ):
            await event.reply(
                "❌ این کامند مخصوص PV است "
                "و نمی‌تواند روی گروه اجرا شود."
            )

            invocation.mark_handled()
            return

        if group_id is None:
            await event.reply(
                "❌ شناسه گروه نامعتبر است."
            )

            invocation.mark_handled()
            return

        # Context جدید گروه هدف
        remote_event = RemoteGroupEvent(
            client=self.client,
            original_event=event,
            group_id=group_id,
            command_name=invocation.command_name,
            args_text=clean_args,
        )

        # آرگومان واقعی Command را بدون target
        # جایگزین می‌کنیم.
        invocation.set_args(
            clean_args
        )

        invocation.replace_event(
            remote_event
        )

        # این Invocation از PV Owner آمده و
        # Group Manager هویت Owner را بررسی کرده است.
        invocation.grant_access()

        # منبع اجرا برای Pluginهایی که لازم دارند
        # قابل تشخیص باشد.
        invocation.source = (
            "group_manager"
        )

        invocation.metadata[
            "group_target"
        ] = group_id

        invocation.metadata[
            "remote"
        ] = True