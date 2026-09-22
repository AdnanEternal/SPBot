from __future__ import annotations

import re

from core.execution import ExecutionEvent


_GROUP_TARGET_PATTERN = re.compile(
    r"(?:^|\s)group_target=(-?\d+)\s*$",
    re.IGNORECASE,
)

_GROUP_TARGET_FLAG_PATTERN = re.compile(
    r"(?:^|\s)--group-target\s+(-?\d+)\s*$",
    re.IGNORECASE,
)


# Commandهایی که System Plugin اجازه می‌دهد
# با group_target به گروه دیگری Remote شوند.



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

        # فقط Owner می‌تواند از Remote Group Manager استفاده کند.
        from core.permissions import is_owner

        if not is_owner(event.sender_id):
            return

        # فقط Commandهای گروهی قابلیت Remote شدن دارند.
        # Commandهای all/private عمداً Remote نمی‌شوند.
        if invocation.command.chat_type != "group":
            return

        clean_args, group_id, found = (
            self.extract_group_target(
                invocation.args_text
            )
        )

        # group_target نداریم؛ اجرای عادی.
        if not found:
            return

        if group_id is None:
            await event.reply(
                "❌ شناسه گروه نامعتبر است."
            )

            invocation.mark_handled()
            return

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
        )

        invocation.set_args(
            clean_args
        )

        invocation.replace_event(
            remote_event
        )

        # Owner قبلاً بررسی شده.
        invocation.grant_access()

        invocation.source = "group_manager"

        invocation.metadata[
            "group_target"
        ] = group_id

        invocation.metadata[
            "remote"
        ] = True