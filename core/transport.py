from abc import ABC, abstractmethod
from typing import Any, Iterable


class BaseTransport(ABC):
    """Low-level connection interface used by SPBot Core."""

    # ---------------------------------------------------------
    # COMMAND INTERFACE
    # ---------------------------------------------------------

    # Prefix قابل قبول برای اجرای Command
    command_prefix: str = "!"

    # نامی که کاربر باید بعد از prefix وارد کند:
    #
    # name        -> Command.name
    # native_name -> Command.native_name
    command_name_field: str = "name"

    # آیا syntax کامند در متن به‌شکل قابل‌کپی نمایش داده شود؟
    command_display_backticks: bool = True
    
    # آیا این Transport از Inline Button پشتیبانی می‌کند؟
    supports_inline_buttons: bool = False

    @abstractmethod
    async def start(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_client(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def sync_commands(
        self,
        commands: Iterable[Any],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def clear_commands(self) -> None:
        raise NotImplementedError