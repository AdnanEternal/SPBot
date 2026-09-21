from __future__ import annotations

import re

from core.execution import ExecutionEvent, Output


_GROUP_TARGET_PATTERN = re.compile(
    r"(?:^|\s)group_target=(-?\d+)\s*$",
    re.IGNORECASE,
)

_GROUP_TARGET_FLAG_PATTERN = re.compile(
    r"(?:^|\s)--group-target\s+(-?\d+)\s*$",
    re.IGNORECASE,
)


class GroupManager:
    """
    مدیریت اجرای Remote Command برای یک گروه مشخص.
    """

    def __init__(self, client) -> None:
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
        """

        text = (args_text or "").strip()

        if not text:
            return "", None, False

        match = _GROUP_TARGET_PATTERN.search(text)

        if match:
            group_id = int(match.group(1))

            clean = text[:match.start()].strip()

            return clean, group_id, True

        match = _GROUP_TARGET_FLAG_PATTERN.search(text)

        if match:
            group_id = int(match.group(1))

            clean = text[:match.start()].strip()

            return clean, group_id, True

        return text, None, False

    async def handle_invocation(
        self,
        invocation,
    ) -> None:
        event = invocation.original_event

        # فقط از PV
        if not getattr(
            event,
            "is_private",
            False,
        ):
            return

        # فقط Owner
        from core.permissions import is_owner

        if not is_owner(event.sender_id):
            return

        clean_args, group_id, found = (
            self.extract_group_target(
                invocation.args_text
            )
        )

        # target نداریم؛ اجرای عادی
        if not found:
            return

        # Commandهای private-only را نمی‌توان
        # روی گروه اجرا کرد.
        if invocation.command.chat_type == "private":
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

        # ساخت Execution Event جدید برای اجرای
        # Command در گروه هدف
        remote_event = ExecutionEvent(
            self.client,
            base=event,
            chat_id=group_id,
            is_group=True,
            args_text=clean_args,
            raw_text=(
                f"!{invocation.command_name}"
                + (
                    f" {clean_args}"
                    if clean_args
                    else ""
                )
            ),
            output=Output.origin(),
        )

        # آرگومان واقعی Command
        # بدون group_target
        invocation.set_args(
            clean_args
        )

        # Context اجرای Command را عوض می‌کنیم
        invocation.replace_event(
            remote_event
        )

        # Owner قبلاً بررسی شده
        invocation.grant_access()

        invocation.source = "group_manager"

        invocation.metadata[
            "group_target"
        ] = group_id

        invocation.metadata[
            "remote"
        ] = True