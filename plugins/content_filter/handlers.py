from splusthon import events

from core.decorators import command, on_event


@command(name="فیلتر", permission="admin", chat_type="group")
async def add_word(self, event):
    word = event.args_text
    if not word:
        await event.reply("مثال: !فیلتر کلمه")
        return

    await self.words.add(event.chat_id, word)
    await event.reply(f"کلمه «{word}» به لیست فیلتر این گروه اضافه شد.")


@command(name="حذففیلتر", permission="admin", chat_type="group")
async def remove_word(self, event):
    word = event.args_text
    if not word:
        await event.reply("مثال: !حذففیلتر کلمه")
        return

    await self.words.remove(event.chat_id, word)
    await event.reply(f"کلمه «{word}» از لیست فیلتر این گروه حذف شد.")


@command(name="ب", permission="admin", chat_type="group")
async def list_words(self, event):
    words = await self.words.get_all(event.chat_id)
    if not words:
        await event.reply("لیست فیلتر این گروه خالیه.")
        return

    await event.reply("کلمات فیلترشده:\n" + "\n".join(sorted(words)))


@on_event(events.NewMessage(incoming=True))
async def on_message(self, event):
    if not event.is_group:
        return

    if await self.words.contains(event.chat_id, event.raw_text or ""):
        await event.delete()
