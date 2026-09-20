from splusthon import events
from core.decorators import command, on_bus_event, on_event
from .gateway import AIGatewayError
from .trigger import extract_trigger_text

import traceback

def mask_secret(secret):
    if not secret: return 'تنظیم نشده'
    if len(secret) <= 8: return '••••••••'
    return f'{secret[:4]}••••{secret[-4:]}'



@command(
    name="کلید افزودن",
    permission="owner",
    chat_type="all",
    description="یک API Key را برای استفاده و مدیریت ذخیره می‌کند.",
)
async def add_api_key(
    self,
    event,
):
    args = (event.args_text or "").strip().split()

    if len(args) < 3:
        await event.reply(
            "مثال:\n"
            "!کلید افزودن zai openai API_KEY BASE_URL [MODELS_URL]"
        )
        return

    name = args[0]
    provider = args[1]
    api_key = args[2]

    base_url = (
        args[3]
        if len(args) >= 4
        else None
    )

    models_url = (
        args[4]
        if len(args) >= 5
        else None
    )

    try:
        await self.api_keys.add(
            name=name,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            models_url=models_url,
        )

    except Exception as exc:
        await event.reply(
            f"❌ ذخیره API Key ناموفق بود:\n{exc}"
        )
        return

    try:
        await event.delete()
    except Exception:
        pass

    await event.reply(
        f"✅ API Key «{name}» ذخیره شد."
    )


@command(
    name="کلید ها",
    permission="owner",
    chat_type="all",
    description="لیست API Keyهای ذخیره‌شده را نشان می‌دهد.",
)
async def list_api_keys(
    self,
    event,
):
    keys = await self.api_keys.get_all()

    if not keys:
        await event.reply(
            "🔑 هیچ API Key ذخیره نشده است."
        )
        return

    lines = []

    for item in keys:
        lines.append(
            f"🔑 `{item['name']}` — "
            f"{item['provider']}"
        )

    await event.reply(
        "🔐 API Keyهای ذخیره‌شده:\n\n"
        + "\n".join(lines)
    )


@command(
    name="کلید حذف",
    permission="owner",
    chat_type="all",
    description="یک API Key را حذف می‌کند.",
)
async def delete_api_key(
    self,
    event,
):
    name = (event.args_text or "").strip()

    if not name:
        await event.reply(
            "مثال: !کلید حذف zai"
        )
        return

    if not await self.api_keys.delete(name):
        await event.reply(
            f"❌ API Key «{name}» پیدا نشد."
        )
        return

    await event.reply(
        f"✅ API Key «{name}» حذف شد."
    )


@command(
    name="کلید مدل ها",
    permission="owner",
    chat_type="all",
    description="مدل‌های موجود روی API را بدون Ping نشان می‌دهد.",
)
async def api_key_models(
    self,
    event,
):
    name = (event.args_text or "").strip()

    if not name:
        await event.reply(
            "مثال: !کلید مدل ها zai"
        )
        return

    api_key = await self.api_keys.get(name)

    if api_key is None:
        await event.reply(
            f"❌ API Key «{name}» پیدا نشد."
        )
        return

    try:
        models = await self.gateway.list_remote_models(
            api_key
        )

    except AIGatewayError as exc:
        await event.reply(
            f"❌ نتونستم مدل‌های «{name}» رو بگیرم:\n"
            f"{exc}"
        )
        return

    if not models:
        await event.reply(
            "📦 این API هیچ مدلی برنگردوند."
        )
        return

    lines = [
        f"🔹 `{model}`"
        for model in models
    ]

    await event.reply(
        f"📦 مدل‌های API «{name}»:\n\n"
        + "\n".join(lines)
    )



@command(
    name="حافظه پاک",
    permission="owner",
    chat_type="group",
    description="تمام حافظه و خلاصه‌ی بوبی در این گروه را پاک می‌کند.",
)
async def clear_memory(
    self,
    event: events.NewMessage.Event,
) -> None:
    try:
        await self.memory.store.clear_group(
            event.chat_id
        )

    except Exception as exc:
        print(
            f"❌ خطا در پاک کردن حافظه گروه "
            f"{event.chat_id}: {exc}"
        )

        await event.reply(
            "❌ پاک کردن حافظه ناموفق بود."
        )
        return

    await event.reply(
        "🧠 حافظه‌ی بوبی در این گروه کامل پاک شد."
    )

@command(
    name="کلید مدل ها پینگ",
    permission="owner",
    chat_type="all",
    description="مدل‌های API را همزمان Ping می‌کند.",
)
async def api_key_models_ping(
    self,
    event,
):
    name = (event.args_text or "").strip()

    if not name:
        await event.reply(
            "مثال: !کلید مدل ها پینگ zai"
        )
        return

    api_key = await self.api_keys.get(name)

    if api_key is None:
        await event.reply(
            f"❌ API Key «{name}» پیدا نشد."
        )
        return

    try:
        models = await self.gateway.list_remote_models(
            api_key
        )

    except AIGatewayError as exc:
        await event.reply(
            f"❌ دریافت مدل‌ها ناموفق بود:\n{exc}"
        )
        return

    if not models:
        await event.reply(
            "📦 هیچ مدلی برای Ping پیدا نشد."
        )
        return

    await event.reply(
        f"📡 در حال Ping کردن {len(models)} مدل..."
    )

    try:
        results = await self.gateway.ping_remote_models(
            api_key,
            models,
        )

    except Exception as exc:
        await event.reply(
            f"❌ اجرای Ping ناموفق بود:\n{exc}"
        )
        return

    lines = [
        f"📡 نتیجه Ping برای `{name}`:",
        "",
    ]

    for model_id, ok, latency, error in results:
        if ok:
            lines.append(
                f"✅ `{model_id}` — {latency:.0f}ms"
            )
        else:
            error = str(error).replace(
                "\n",
                " ",
            ).strip()

            if len(error) > 100:
                error = error[:97] + "..."

            lines.append(
                f"❌ `{model_id}` — "
                f"{latency:.0f}ms — {error}"
            )

    # پیام‌ها را به چند قسمت تقسیم می‌کنیم
    # تا از محدودیت طول پیام رد نشویم.
    chunk_size = 3000
    chunks = []
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > chunk_size:
            if current:
                chunks.append(current)

            current = line
        else:
            if current:
                current += "\n"

            current += line

    if current:
        chunks.append(current)

    for chunk in chunks:
        try:
            await event.reply(chunk)
        except Exception as exc:
            print(
                f"❌ خطا در ارسال نتیجه Ping: {exc}"
            )
            break



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


@command(
    name="حافظه پیام",
    permission="owner",
    chat_type="group",
    description="حداکثر تعداد پیام ذخیره‌شده حافظه این گروه را تنظیم می‌کند.",
)
async def memory_message_limit(
    self,
    event: events.NewMessage.Event,
) -> None:
    value = (event.args_text or "").strip()

    if not value:
        limit = await self.memory.settings.get_message_limit(
            event.chat_id
        )

        await event.reply(
            f"🗃️ سقف پیام‌های ذخیره‌شده این گروه: {limit:,} پیام"
        )
        return

    if not value.isdigit():
        await event.reply(
            "مثال:\n"
            "!حافظه پیام 500"
        )
        return

    limit = int(value)

    if limit < 10:
        await event.reply(
            "❌ حداقل تعداد پیام 10 است."
        )
        return

    await self.memory.settings.set_message_limit(
        event.chat_id,
        limit,
    )

    # اگر مقدار جدید کمتر از تعداد فعلی باشد،
    # همین الان حافظه اضافی حذف شود.
    await self.memory.trim(
        event.chat_id
    )

    await event.reply(
        f"✅ سقف پیام‌های حافظه روی "
        f"{limit:,} پیام تنظیم شد."
    )




@command(
    name="مدل افزودن",
    permission="owner",
    chat_type="all",
    description="افزودن مدل AI با استفاده از API Key ذخیره‌شده یا اطلاعات کامل.",
)
async def add_model(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if not args:
        await event.reply(
            "فرمت‌ها:\n\n"
            "🔹 استفاده از API Key ذخیره‌شده:\n"
            "!مدل افزودن <نام_مدل> <نام_API_Key> <model_id>\n\n"
            "مثال:\n"
            "!مدل افزودن gpt5 zai glm-4.5\n\n"
            "🔹 وارد کردن اطلاعات کامل:\n"
            "!مدل افزودن <نام_مدل> <provider> <model_id> <API_KEY> [BASE_URL]"
        )
        return

    # -------------------------------------------------
    # حالت جدید:
    # !مدل افزودن gpt5 zai glm-4.5
    # -------------------------------------------------
    if len(args) == 3:
        model_name = args[0]
        api_key_name = args[1]
        model_id = args[2]

        api_key_data = await self.api_keys.get(
            api_key_name
        )

        if api_key_data is None:
            await event.reply(
                f"❌ API Key «{api_key_name}» پیدا نشد."
            )
            return

        provider = api_key_data["provider"]
        api_key = api_key_data["api_key"]
        base_url = api_key_data["base_url"]

        try:
            await self.models.add(
                name=model_name,
                provider=provider,
                model_id=model_id,
                api_key=api_key,
                base_url=base_url,
            )

        except Exception as exc:
            await event.reply(
                f"❌ خطا در افزودن مدل:\n{exc}"
            )
            return

        try:
            await event.delete()
        except Exception:
            pass

        await event.reply(
            f"✅ مدل «{model_name}» اضافه شد.\n"
            f"🔑 API Key: {api_key_name}\n"
            f"🤖 Model ID: {model_id}"
        )

        return

    # -------------------------------------------------
    # حالت قدیمی:
    # !مدل افزودن gpt openai gpt-4o-mini API_KEY BASE_URL
    # -------------------------------------------------
    if len(args) < 4:
        await event.reply(
            "❌ پارامترهای کافی وارد نشده.\n\n"
            "استفاده از API Key ذخیره‌شده:\n"
            "!مدل افزودن <نام_مدل> <نام_API_Key> <model_id>\n\n"
            "یا اطلاعات کامل:\n"
            "!مدل افزودن <نام_مدل> <provider> <model_id> <API_KEY> [BASE_URL]"
        )
        return

    model_name = args[0]
    provider = args[1]
    model_id = args[2]
    api_key = args[3]

    base_url = (
        args[4]
        if len(args) >= 5
        else None
    )

    try:
        await self.models.add(
            name=model_name,
            provider=provider,
            model_id=model_id,
            api_key=(
                None
                if api_key == "-"
                else api_key
            ),
            base_url=base_url,
        )

    except Exception as exc:
        await event.reply(
            f"❌ خطا در افزودن مدل:\n{exc}"
        )
        return

    try:
        await event.delete()
    except Exception:
        pass

    await event.reply(
        f"✅ مدل «{model_name}» اضافه شد."
    )

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




@command(
    name="تایم لاین",
    permission="owner",
    chat_type="all",
    description="خاموش یا روشن کردن سراسری Timeline هوش مصنوعی",
)
async def timeline_toggle(
    self,
    event,
):
    value = (
        event.args_text or ""
    ).strip().lower()

    if not value:
        status = (
            "🟢 فعال"
            if self.timeline_enabled
            else "🔴 خاموش"
        )

        await event.reply(
            f"🧭 وضعیت Timeline سراسری: {status}\n\n"
            "روشن کردن:\n"
            "!تایم لاین روشن\n\n"
            "خاموش کردن:\n"
            "!تایم لاین خاموش"
        )
        return

    if value in {
        "روشن",
        "on",
        "1",
        "فعال",
    }:
        self.timeline_enabled = True

        await event.reply(
            "✅ Timeline سراسری روشن شد."
        )
        return

    if value in {
        "خاموش",
        "off",
        "0",
        "غیرفعال",
    }:
        self.timeline_enabled = False

        # چون دیگر استفاده‌ای از Timelineها نداریم،
        # RAM را هم آزاد می‌کنیم.
        self.memory.clear_all_timelines()

        await event.reply(
            "🛑 Timeline سراسری خاموش شد و "
            "Timelineهای موجود از RAM پاک شدند."
        )
        return

    await event.reply(
        "❌ مقدار نامعتبر.\n\n"
        "استفاده:\n"
        "!تایم لاین روشن\n"
        "!تایم لاین خاموش"
    )








@command(
    name="نمایش تایم لاین",
    permission="owner",
    chat_type="group",
    description="محتوای فعلی Timeline این گروه رو (همونی که بوبی می‌بینه) نشون می‌ده - برای دیباگ.",
)
async def show_timeline(self, event) -> None:
    context = self.memory.get_timeline_context(event.chat_id)

    if not context:
        await event.reply(
            "🧭 Timeline این گروه خالیه یا لود نشده.\n"
            "با !تاریخچه {عدد} لودش کن."
        )
        return

    # همون الگوی تقسیم پیام که تو "کلید مدل ها پینگ" هست، که وسط یه
    # خط قطع نشه و به محدودیت طول پیام هم نخوریم.
    lines = context.split("\n")
    chunk_size = 3000
    chunks = []
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > chunk_size:
            if current:
                chunks.append(current)
            current = line
        else:
            if current:
                current += "\n"
            current += line

    if current:
        chunks.append(current)

    for chunk in chunks:
        try:
            await event.reply(chunk)
        except Exception as exc:
            print(f"❌ خطا در ارسال Timeline: {exc}")
            break


@command(
    name="پاک تایم لاین",
    permission="owner",
    chat_type="group",
    description="Timeline این گروه رو کامل از RAM پاک می‌کنه - برای دیباگ.",
)
async def clear_timeline_command(self, event) -> None:
    self.memory.clear_timeline(event.chat_id)
    await event.reply("🧹 Timeline این گروه پاک شد.")





@command(
    name="تاریخچه",
    permission="owner",
    chat_type="group",
    description="تعداد مشخصی از پیام‌های اخیر را در Timeline RAM آماده می‌کند.",
)
async def load_timeline(
    self,
    event,
):
    if not self.timeline_enabled:
        await event.reply(
            "🛑 Timeline در حال حاضر خاموش است.\n"
            "اول بزن:\n"
            "!تایم لاین روشن"
        )
        return

    value = (
        event.args_text or ""
    ).strip()

    if not value.isdigit():
        await event.reply(
            "مثال:\n"
            "!تاریخچه 200"
        )
        return

    limit = int(value)

    if limit < 10:
        await event.reply(
            "❌ حداقل تعداد پیام 10 است."
        )
        return

    if limit > self.memory.MAX_TIMELINE_MESSAGES:
        await event.reply(
            f"❌ حداکثر تعداد پیام "
            f"{self.memory.MAX_TIMELINE_MESSAGES} است."
        )
        return

    try:
        count = await self.memory.load_timeline(
            self.client,
            event.chat_id,
            limit,
        )

    except Exception as exc:
        print(
            "❌ خطا در بارگذاری Timeline:",
            exc,
        )

        await event.reply(
            "❌ نتونستم تاریخچه گروه را بارگذاری کنم."
        )
        return

    await event.reply(
        f"🧭 Timeline آماده شد.\n"
        f"📦 {count} پیام در RAM نگه داشته می‌شود.\n\n"
        f"از این لحظه پیام‌های جدید هم "
        f"به‌صورت خودکار ثبت می‌شوند."
    )


@on_event(events.NewMessage(incoming=True))
async def on_timeline_incoming(
    self,
    event,
):
    try:
        if not self.timeline_enabled:
            return

        if not event.is_group:
            return

        await self.memory.record_event(
            event
        )

    except Exception:
        traceback.print_exc()


@on_event(events.NewMessage(outgoing=True))
async def on_timeline_outgoing(
    self,
    event,
):
    try:
        if not self.timeline_enabled:
            return

        if not event.is_group:
            return

        await self.memory.record_event(
            event
        )

    except Exception:
        traceback.print_exc()









@on_event(events.NewMessage(incoming=True))
async def on_message(self, event):
    try:
        if not event.is_group:
            return

        text = (
            event.raw_text or ""
        ).strip()

        if not text or text.startswith("!"):
            return

        if event.sender_id is None:
            return

        trigger = await self.groups.get_trigger(
            event.chat_id,
            self.default_trigger,
        )

        prompt_text = extract_trigger_text(
            text,
            trigger,
        )

        current_reply_context = (
            await self.memory.get_current_reply_context(
                event
            )
        )


        if event.is_reply:

            try:
                replied = (
                    await event.get_reply_message()
                )

            except Exception:
                replied = None

            if (
                replied is not None
                and replied.sender_id
                == self.bot_user_id
            ):
                prompt_text = text

        if prompt_text is None:
            return

        try:
            sender = await event.get_sender()

            name = (
                getattr(
                    sender,
                    "username",
                    None,
                )
                or getattr(
                    sender,
                    "first_name",
                    None,
                )
                or str(event.sender_id)
            )

        except Exception:
            name = str(event.sender_id)

        user_content = (
            self.memory.format_user_message(
                name,
                int(event.sender_id),
                prompt_text,
            )
        )

        if current_reply_context:
            user_content = (
                current_reply_context
                + "\n\n"
                + user_content
            )

        await self.memory.store.add_message(
            event.chat_id,
            "user",
            user_content,
            event.sender_id,
        )

        # حافظه را حتی اگر AI بعداً Fail شد هم محدود نگه می‌داریم.
        await self.memory.maybe_trim(
            event.chat_id
        )

        context = await self.memory.build_context(
            event.chat_id,
            await self.groups.get_system_prompt(
                event.chat_id
            ),
            self.gateway,
            current_reply_context=current_reply_context,
        )

        answer = await self.gateway.chat(
            context
        )

        await self.memory.store.add_message(
            event.chat_id,
            "assistant",
            answer,
        )

        await event.reply(
            answer[:4000]
        )

    except AIGatewayError as exc:
        print(
            f"❌ AI Gateway: {exc}"
        )

        try:
            await event.reply(
                "❌ بوبی فعلاً نتونست پاسخ بده. "
                "لطفاً دوباره امتحان کن."
            )
        except Exception:
            pass

    except Exception:
        print(
            "❌ خطای غیرمنتظره در "
            "AI Message Handler:"
        )
        traceback.print_exc()

        try:
            await event.reply(
                "❌ هنگام پردازش پیام مشکلی پیش آمد."
            )
        except Exception:
            pass



@on_bus_event("violation")
async def on_violation_deleted(
    self,
    event,
    group_id: int,
    user_id: int,
    reason: str,
) -> None:
    """
    وقتی یه پلاگین دیگه یه پیام رو به‌خاطر تخلف پاک می‌کنه، فقط
    Timeline رو آپدیت می‌کنیم - نه چیز دیگه‌ای.
    """
    if not self.timeline_enabled:
        return

    self.memory.mark_deleted(group_id, event, reason)