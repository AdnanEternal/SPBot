from . import handlers
from .store import GroupSettingsStore, ViolationStore

from core.base_plugin import BasePlugin
from core.ttl_cache import TTLCache

class ViolationNoticeThrottle:
    """
    جلوگیری از ارسال اخطارهای تکراری.

    ثبت تخلف و مجازات هیچ تغییری نمی‌کنند؛
    فقط پیام عمومی ربات throttle می‌شود.
    """

    TTL_SECONDS = 30
    MAX_ENTRIES = 5000

    def __init__(self) -> None:
        self._cache = TTLCache[
            tuple[int, int, str],
            bool,
        ](
            max_entries=self.MAX_ENTRIES,
            ttl_seconds=self.TTL_SECONDS,
        )

    def should_notify(
        self,
        group_id: int,
        user_id: int,
        category: str,
    ) -> bool:
        key = (
            group_id,
            user_id,
            str(category).casefold().strip(),
        )

        if self._cache.get(key):
            return False

        self._cache.set(
            key,
            True,
        )

        return True

class ViolationManagerPlugin(BasePlugin):
    name = "Violation Manager"
    version = "1.6.6"

    def __init__(
        self,
        client,
        command_manager,
        db,
        event_bus,
    ):
        super().__init__(
            client,
            command_manager,
            db,
            event_bus,
        )

        self.violations = ViolationStore(
            self.db
        )

        self.settings = GroupSettingsStore(
            self.db
        )

        self.notice_throttle = (
            ViolationNoticeThrottle()
        )

    async def on_load(self):
        await self.violations.create_table()
        await self.settings.create_table()

    list_violators = handlers.list_violators
    set_max_violations = handlers.set_max_violations
    set_punishment_mute = handlers.set_punishment_mute
    set_punishment_ban = handlers.set_punishment_ban
    my_record = handlers.my_record
    mute_command = handlers.mute_command
    unmute_command = handlers.unmute_command
    on_reply_shortcut = handlers.on_reply_shortcut
    on_violation = handlers.on_violation
    clear_record = handlers.clear_record