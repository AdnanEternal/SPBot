# core/command_manager.py

import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional

from splusthon import SoroushClient, events
from splusthon.events import StopPropagation

from core.permissions import is_chat_admin, is_owner


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
        self.prefix = "!"

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
                f"⚠️ کامند '{name}' قبلاً توسط "
                f"پلاگین '{owner_name}' ثبت شده بود "
                f"و حالا بازنویسی می‌شه."
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

    def _match_command(
        self,
        body: str,
    ) -> tuple[Optional[str], str]:

        best_name: Optional[str] = None

        for name in self.commands:
            if body == name or body.startswith(name + " "):
                if (
                    best_name is None
                    or len(name) > len(best_name)
                ):
                    best_name = name

        if best_name is None:
            return None, ""

        args_text = body[len(best_name):].strip()

        return best_name, args_text

    def register_dispatcher(
        self,
        client: SoroushClient,
    ) -> None:

        @client.on(events.NewMessage(incoming=True))
        async def dispatcher(
            event: events.NewMessage.Event,
        ) -> None:
            command_name = "نامشخص"
            handled = False

            try:
                text = event.raw_text

                if not text or not text.startswith(self.prefix):
                    return

                body = text[len(self.prefix):]

                if not body:
                    return

                matched_name, args_text = self._match_command(body)

                if matched_name is None:
                    return

                command_name = matched_name
                command = self.get_command(command_name)

                if command is None:
                    return

                if command.chat_type == "group" and not event.is_group:
                    return

                if command.chat_type == "private" and not event.is_private:
                    return

                sender_id = event.sender_id

                if command.permission == "admin":
                    chat = await event.get_chat()

                    if not await is_chat_admin(
                        client,
                        chat,
                        sender_id,
                    ):
                        return

                elif command.permission == "owner":
                    if not is_owner(sender_id):
                        return

                event.args_text = args_text
                event.args = args_text.split() if args_text else []

                # فقط از این‌جا به بعد کامند واقعاً اجرا می‌شه و
                # پیام نباید به هندلرهای دیگه (فیلترها و ...) برسه.
                handled = True

                try:
                    await command.handler(event)

                except Exception:
                    print(
                        f"\n❌ خطای بحرانی در اجرای دستور "
                        f"'{command_name}'"
                    )
                    traceback.print_exc()

                    try:
                        await event.reply(
                            "❌ هنگام اجرای این دستور خطایی رخ داد."
                        )
                    except Exception:
                        pass

            except StopPropagation:
                raise

            except Exception:
                print(
                    f"\n❌ خطای بحرانی در Command Dispatcher "
                    f"'{command_name}'"
                )
                traceback.print_exc()

                try:
                    await event.reply(
                        "❌ هنگام پردازش این پیام خطایی رخ داد."
                    )
                except Exception:
                    pass

            finally:
                if handled:
                    raise StopPropagation

        self._dispatcher = dispatcher