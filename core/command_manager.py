from dataclasses import dataclass
from typing import Callable

from splusthon import events

from core.permissions import is_chat_admin


@dataclass
class Command:
    name: str
    handler: Callable
    permission: str = "everyone"
    chat_type: str = "all"
    plugin: object = None


class CommandManager:
    def __init__(self):
        self.commands = {}
        self.prefix = "!"

    def add_command(
        self,
        name: str,
        handler: Callable,
        permission: str = "everyone",
        chat_type: str = "all",
        plugin=None,
    ):
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
            plugin=plugin,
        )

    def get_command(self, name: str):
        return self.commands.get(name)

    def remove_command(self, name: str):
        self.commands.pop(name, None)

    def remove_plugin_commands(self, plugin):
        commands_to_remove = [
            name
            for name, command in self.commands.items()
            if command.plugin is plugin
        ]

        for name in commands_to_remove:
            self.remove_command(name)

    def get_all_commands(self):
        return self.commands.values()

    def register_dispatcher(self, client):
        @client.on(events.NewMessage(incoming=True))
        async def dispatcher(event):
            text = event.raw_text

            if not text or not text.startswith(self.prefix):
                return

            body = text[len(self.prefix):]
            parts = body.split(maxsplit=1)
            if not parts:
                return

            command_name = parts[0]
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

            # آرگومان‌های بعد از نام کامند رو هم به‌صورت متن خام هم لیست
            # روی خود event می‌ذاریم تا هندلرها مجبور نباشن دستی prefix/نام
            # کامند رو از متن جدا کنن.
            event.args_text = parts[1].strip() if len(parts) > 1 else ""
            event.args = event.args_text.split() if event.args_text else []

            try:
                await command.handler(event)
            except Exception as e:
                print(f"❌ خطا در اجرای دستور '{command_name}': {e}")

        self._dispatcher = dispatcher
