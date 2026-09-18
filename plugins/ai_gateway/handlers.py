from splusthon import events
from core.decorators import command, on_event
from .gateway import AIGatewayError
from .trigger import extract_trigger_text


def mask_secret(secret):
    if not secret: return 'تنظیم نشده'
    if len(secret) <= 8: return '••••••••'
    return f'{secret[:4]}••••{secret[-4:]}'



@command(
    name="حافظه",
    permission="owner",
    chat_type="group",
    description="حداکثر تعداد توکن حافظه مکالمه این گروه را تنظیم می‌کند.",
)
async def memory_limit(
    self,
    event: events.NewMessage.Event,
) -> None:
    value = (event.args_text or "").strip()

    if not value:
        limit = await self.memory.settings.get_token_limit(
            event.chat_id
        )

        await event.reply(
            f"🧠 سقف حافظه این گروه: {limit:,} توکن"
        )
        return

    if not value.isdigit():
        await event.reply(
            "مثال:\n"
            "!حافظه 8000"
        )
        return

    limit = int(value)

    if limit < 100:
        await event.reply(
            "❌ حداقل مقدار حافظه 100 توکن است."
        )
        return

    await self.memory.settings.set_token_limit(
        event.chat_id,
        limit,
    )

    await event.reply(
        f"✅ سقف حافظه این گروه روی "
        f"{limit:,} توکن تنظیم شد."
    )


@command(name='مدل افزودن', permission='owner', chat_type='all', description='افزودن مدل AI')
async def add_model(self, event):
    args = (event.args_text or '').split()
    if len(args) < 4:
        await event.reply('مثال: !مدل افزودن gpt openai gpt-4o-mini API_KEY [BASE_URL]')
        return
    name, provider, model_id, key = args[:4]
    base_url = args[4] if len(args) > 4 else None
    try:
        await self.models.add(name, provider, model_id, None if key == '-' else key, base_url)
    except Exception as exc:
        await event.reply(f'❌ خطا: {exc}')
        return
    try: await event.delete()
    except Exception: pass
    await event.reply(f'✅ مدل «{name}» اضافه شد.')


@command(name='مدل ها', permission='owner', chat_type='all', description='لیست مدل ها')
async def list_models(self, event):
    models = await self.models.get_all()
    if not models:
        await event.reply('📦 هیچ مدلی ثبت نشده.')
        return
    await event.reply('🤖 مدل ها:\n\n' + '\n'.join(f"{'🟢' if m['is_active'] else '⚪'} {m['name']} — {m['provider']}/{m['model_id']}" for m in models))


@command(name='مدل فعال', permission='owner', chat_type='all', description='فعال کردن یا دیدن مدل فعال')
async def activate_model(self, event):
    name = (event.args_text or '').strip()
    if not name:
        m = await self.models.get_active()
        await event.reply('ℹ️ مدل فعالی وجود ندارد.' if not m else f"🟢 {m['name']} — {m['provider']}/{m['model_id']}")
        return
    if not await self.models.set_active(name):
        await event.reply(f'❌ مدل «{name}» پیدا نشد.')
        return
    await event.reply(f'✅ مدل «{name}» فعال شد.')


@command(name='مدل حذف', permission='owner', chat_type='all', description='حذف مدل')
async def delete_model(self, event):
    name = (event.args_text or '').strip()
    if not name:
        await event.reply('مثال: !مدل حذف gpt')
        return
    if not await self.models.delete(name):
        await event.reply(f'❌ مدل «{name}» پیدا نشد.')
        return
    await event.reply(f'✅ مدل «{name}» حذف شد.')


@command(name='مدل اطلاعات', permission='owner', chat_type='all', description='جزئیات مدل')
async def model_info(self, event):
    name = (event.args_text or '').strip()
    m = await self.models.get(name)
    if not m:
        await event.reply('❌ مدل پیدا نشد.')
        return
    await event.reply(f"🤖 {m['name']}\nProvider: {m['provider']}\nModel ID: {m['model_id']}\nBase URL: {m['base_url'] or 'پیش فرض'}\nAPI Key: {mask_secret(m['api_key'])}\nActive: {'بله' if m['is_active'] else 'خیر'}")


@command(name='مدل کلید', permission='owner', chat_type='all', description='تغییر API Key')
async def update_model_key(self, event):
    args = (event.args_text or '').split()
    if len(args) != 2:
        await event.reply('مثال: !مدل کلید gpt NEW_API_KEY')
        return
    if not await self.models.update_api_key(args[0], None if args[1] == '-' else args[1]):
        await event.reply('❌ مدل پیدا نشد.')
        return
    try: await event.delete()
    except Exception: pass
    await event.reply('✅ API Key بروزرسانی شد.')


@command(
        name='مدل پینگ', 
        permission='owner', 
        chat_type='all', 
        description='تست مدل ها')
async def ping_models(self, event):
    target = (event.args_text or '').strip()
    models = [await self.models.get(target)] if target else await self.models.get_all()
    models = [m for m in models if m]
    if not models:
        await event.reply('📡 مدلی برای Ping وجود ندارد.')
        return
    lines = ['📡 نتیجه Ping:']
    for m in models:
        ok, latency, error = await self.gateway.ping(m)
        line = f"{'✅' if ok else '❌'} {m['name']} — {latency:.0f}ms"
        if not ok: line += ' — ' + error[:120].replace('\n', ' ')
        lines.append(line)
    await event.reply('\n'.join(lines))


@command(
        name='پرامپت', 
        permission='owner', 
        chat_type='all', 
        description='دیدن System Prompt'
        )
async def show_prompt(self, event):
    await event.reply('🧠 System Prompt:\n\n' + await self.groups.get_system_prompt(event.chat_id))


@command(
        name='پرامپت تنظیم', 
        permission='owner', 
        chat_type='all', 
        description='تغییر System Prompt'
        )
async def set_prompt(self, event):
    prompt = (event.args_text or '').strip()
    if not prompt:
        await event.reply('مثال: !پرامپت تنظیم تو بوبی هستی')
        return
    await self.groups.set_system_prompt(event.chat_id, prompt)
    await event.reply('✅ System Prompt تغییر کرد.')


@command(
        name='پرامپت ریست', 
        permission='owner', 
        chat_type='all', 
        description='بازگردانی System Prompt'
)
async def reset_prompt(self, event):
    await self.groups.reset_system_prompt(event.chat_id)
    await event.reply('✅ System Prompt ریست شد.')


@command(
        name='نام ربات', 
        permission='owner', 
        chat_type='all', 
        description='دیدن یا تغییر Trigger'
        )
async def bot_name(self, event):
    value = (event.args_text or '').strip()
    if not value:
        await event.reply(f"🏷️ Trigger: {await self.groups.get_trigger(event.chat_id, self.default_trigger)}")
        return
    await self.groups.set_trigger(event.chat_id, value)
    await event.reply(f'✅ Trigger شد: {value}')


@on_event(events.NewMessage(incoming=True))
async def on_message(self, event):
    if not event.is_group:
        return
    text = (event.raw_text or '').strip()
    if not text or text.startswith('!'):
        return
    trigger = await self.groups.get_trigger(event.chat_id, self.default_trigger)
    prompt_text = extract_trigger_text(text, trigger)
    if event.is_reply:
        try: replied = await event.get_reply_message()
        except Exception: replied = None
        if replied is not None and replied.sender_id == self.bot_user_id:
            prompt_text = text
    if prompt_text is None:
        return
    try:
        sender = await event.get_sender()
        name = getattr(sender, 'username', None) or getattr(sender, 'first_name', None) or str(event.sender_id)
    except Exception:
        name = str(event.sender_id)
    user_content = self.memory.format_user_message(name, int(event.sender_id), prompt_text)
    await self.memory.store.add_message(event.chat_id, 'user', user_content, event.sender_id)

    context = await self.memory.build_context(
        event.chat_id,
        await self.groups.get_system_prompt(event.chat_id),
        self.gateway,
    )

    try:
        answer = await self.gateway.chat(context)

    except AIGatewayError as exc:
        print(f"❌ AI Gateway: {exc}")

        await event.reply(
            "❌ بوبی فعلاً نتونست پاسخ بده. "
            "لطفاً دوباره امتحان کن."
        )
        return

    except Exception as exc:
        print(f"❌ خطای غیرمنتظره AI Gateway: {exc}")

        await event.reply(
            "❌ بوبی فعلاً نتونست پاسخ بده. "
            "لطفاً دوباره امتحان کن."
        )
        return
    await self.memory.store.add_message(event.chat_id, 'assistant', answer)
    await event.reply(answer[:4000] if len(answer) > 4000 else answer)
    