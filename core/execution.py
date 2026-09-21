from __future__ import annotations

from typing import Any


class ExecutionEvent:
    """
    Event عمومی برای اجرای Command.

    می‌تواند:
    - بر پایه‌ی یک Event واقعی باشد.
    - Context چت/کاربر را override کند.
    - بدون Event واقعی هم ساخته شود.
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
    ) -> None:
        self.client = client
        self.base = base

        self._chat_id = chat_id
        self._sender_id = sender_id
        self._is_group = is_group
        self._raw_text = raw_text
        self._chat_cache: Any = None

        if args_text is None:
            args_text = getattr(
                base,
                "args_text",
                "",
            ) or ""

        self.args_text = args_text
        self.args = (
            args_text.split()
            if args_text
            else []
        )

    # =========================================================
    # Context
    # =========================================================

    @property
    def chat_id(self) -> int | None:
        if self._chat_id is not None:
            return self._chat_id

        return getattr(
            self.base,
            "chat_id",
            None,
        )

    @property
    def sender_id(self) -> int | None:
        if self._sender_id is not None:
            return self._sender_id

        return getattr(
            self.base,
            "sender_id",
            None,
        )

    @property
    def is_group(self) -> bool:
        if self._is_group is not None:
            return self._is_group

        return bool(
            getattr(
                self.base,
                "is_group",
                False,
            )
        )

    @property
    def is_private(self) -> bool:
        if self._is_group is not None:
            return not self._is_group

        return bool(
            getattr(
                self.base,
                "is_private",
                False,
            )
        )

    @property
    def raw_text(self) -> str:
        if self._raw_text is not None:
            return self._raw_text

        return getattr(
            self.base,
            "raw_text",
            "",
        ) or ""

    @property
    def text(self) -> str:
        return self.raw_text

    @property
    def message(self) -> str:
        return self.raw_text

    @property
    def id(self) -> int | None:
        if self.base is None:
            return None

        if (
            self.chat_id
            != getattr(
                self.base,
                "chat_id",
                None,
            )
        ):
            return None

        return getattr(
            self.base,
            "id",
            None,
        )

    @property
    def is_reply(self) -> bool:
        if self.base is None:
            return False

        if (
            self.chat_id
            != getattr(
                self.base,
                "chat_id",
                None,
            )
        ):
            return False

        return bool(
            getattr(
                self.base,
                "is_reply",
                False,
            )
        )

    # =========================================================
    # Event API
    # =========================================================

    async def get_chat(self) -> Any:
        same_chat = (
            self.base is not None
            and (
                self._chat_id is None
                or self._chat_id
                == getattr(
                    self.base,
                    "chat_id",
                    None,
                )
            )
        )

        if same_chat:
            return await self.base.get_chat()

        if (
            self._chat_cache is None
            and self.chat_id is not None
        ):
            self._chat_cache = (
                await self.client.get_entity(
                    self.chat_id
                )
            )

        return self._chat_cache

    async def get_sender(self) -> Any:
        if (
            self.base is not None
            and (
                self._sender_id is None
                or self._sender_id
                == getattr(
                    self.base,
                    "sender_id",
                    None,
                )
            )
        ):
            return await self.base.get_sender()

        if self.sender_id is None:
            return None

        return await self.client.get_entity(
            self.sender_id
        )

    async def get_reply_message(self) -> Any:
        if self.base is None:
            return None

        if (
            self.chat_id
            != getattr(
                self.base,
                "chat_id",
                None,
            )
        ):
            return None

        return await self.base.get_reply_message()

    async def reply(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.base is not None:
            return await self.base.reply(
                *args,
                **kwargs,
            )

        if self.chat_id is not None:
            return await self.client.send_message(
                self.chat_id,
                *args,
                **kwargs,
            )

        return None

    async def respond(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.base is not None:
            return await self.base.respond(
                *args,
                **kwargs,
            )

        if self.chat_id is not None:
            return await self.client.send_message(
                self.chat_id,
                *args,
                **kwargs,
            )

        return None

    async def delete(self) -> Any:
        if self.base is not None:
            return await self.base.delete()

        return None

    def __getattr__(
        self,
        name: str,
    ) -> Any:
        base = self.__dict__.get(
            "base"
        )

        if base is None:
            raise AttributeError(name)

        return getattr(
            base,
            name,
        )