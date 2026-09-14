from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional

from splusthon import SoroushClient, events

from core.permissions import is_chat_admin

EventHandler = Callable[[Any], Awaitable[Any]]


@dataclass
class Command:
    name: str
    handler: EventHandler
    permission: str = "everyone"
    chat_type: str = "all"
    description: str = ""
    plugin: Optional[object] = None


class CommandManager:
    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}
        self.prefix: str = "!"

    def add_command(
        self,
        name: str,
        handler: EventHandler,
        permission: str = "everyone",
        chat_type: str = "all",
        description: str = "",
        plugin: Optional[object] = None,
    ) -> None:
        if name in self.commands:
            owner = self.commands[name].plugin
            owner_name = owner.name if owner else "نامشخص"
            print(
                f"⚠️ کامند '{name}' قبلاً توسط پلاگین '{owner_name}' ثبت شده "
                f"بود و حالا بازنویسی می‌شه."
            )

        self.commands[name] = Command(
            name=name,
            handler=handler,
            permission=permission,
            chat_type=chat_type,
            description=description,
            plugin=plugin,
        )

    def get_command(self, name: str) -> Optional[Command]:
        return self.commands.get(name)

    def remove_command(self, name: str) -> None:
        self.commands.pop(name, None)

    def remove_plugin_commands(self, plugin: object) -> None:
        commands_to_remove = [
            name
            for name, command in self.commands.items()
            if command.plugin is plugin
        ]

        for name in commands_to_remove:
            self.remove_command(name)

    def get_all_commands(self) -> Iterable[Command]:
        return self.commands.values()

    def _match_command(self, body: str) -> tuple[Optional[str], str]:
        """
        اسم کامندها ممکنه خودشون چند کلمه‌ای باشن (مثلاً "حذف فیلتر").
        قبلاً دیسپچر فقط اولین کلمه‌ی بعد از prefix رو به‌عنوان اسم کامند
        در نظر می‌گرفت، برای همین کامندهای چندکلمه‌ای اصلاً match نمی‌شدن
        و مجبور بودی اسمشون رو بدون فاصله بچسبونی (مثل "حذففیلتر").

        این متد به‌جای اون، بین همه‌ی اسم‌های واقعاً ثبت‌شده می‌گرده و
        طولانی‌ترین اسمی که ابتدای body باهاش match می‌شه رو برمی‌گردونه.
        طولانی‌ترین رو انتخاب می‌کنیم که اگه هم "فیلتر" و هم "فیلتر گروه"
        ثبت شده باشن، با هم قاطی نشن.
        """
        best_name: Optional[str] = None

        for name in self.commands:
            if body == name or body.startswith(name + " "):
                if best_name is None or len(name) > len(best_name):
                    best_name = name

        if best_name is None:
            return None, ""

        args_text = body[len(best_name):].strip()
        return best_name, args_text

    def register_dispatcher(self, client: SoroushClient) -> None:
        @client.on(events.NewMessage(incoming=True))
        async def dispatcher(event: events.NewMessage.Event) -> None:
            text = event.raw_text

            if not text or not text.startswith(self.prefix):
                return

            body = text[len(self.prefix):]
            if not body:
                return

            command_name, args_text = self._match_command(body)
            if command_name is None:
                return

            command = self.get_command(command_name)
            if command is None:
                return

            if command.chat_type == "group" and not event.is_group:
                return
            if command.chat_type == "private" and not event.is_private:
                return

            if command.permission == "admin":
                chat = await event.get_chat()
                sender_id = event.sender_id

                if not await is_chat_admin(client, chat, sender_id):
                    return

            # آرگومان‌های بعد از اسم کامند رو هم به‌صورت متن خام هم لیست
            # روی خود event می‌ذاریم تا هندلرها مجبور نباشن دستی prefix/اسم
            # کامند رو از متن جدا کنن.
            event.args_text = args_text
            event.args = args_text.split() if args_text else []

            try:
                await command.handler(event)
            except Exception as e:
                print(f"❌ خطا در اجرای دستور '{command_name}': {e}")

        self._dispatcher = dispatcher