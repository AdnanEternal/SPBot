from splusthon import events

from core.decorators import command, on_bus_event, on_event

from .gateway import AIGatewayError
from .trigger import extract_trigger_text

import traceback


def _is_remote_group_id(
    value: str,
) -> bool:
    """
    شناسه گروه ریموت را تشخیص می‌دهد.

    شناسه گروه‌های سروش‌پلاس معمولاً منفی هستند،
    بنابراین فقط tokenهای منفی را به‌عنوان مقصد ریموت
    در نظر می‌گیریم تا با آرگومان‌های عددی عادی
    مثل تعداد توکن یا تعداد پیام تداخل نداشته باشند.
    """

    if not value:
        return False

    try:
        return int(value) < 0
    except ValueError:
        return False


def _extract_optional_group_target(
    raw: str,
) -> tuple[int | None, str]:
    """
    اگر آخرین آرگومان یک شناسه گروه منفی باشد،
    آن را به‌عنوان مقصد ریموت جدا می‌کند.

    مثال:

        "8000 -100123"
            -> (-100123, "8000")

        "-100123"
            -> (-100123, "")

        "8000"
            -> (None, "8000")
    """

    parts = raw.strip().split()

    if not parts:
        return None, ""

    candidate = parts[-1]

    if not _is_remote_group_id(candidate):
        return None, raw.strip()

    try:
        target_group = int(candidate)
    except ValueError:
        return None, raw.strip()

    return (
        target_group,
        " ".join(parts[:-1]).strip(),
    )


def _resolve_memory_target(
    event,
) -> tuple[int | None, str, bool]:
    """
    مقصد گروه را برای کامندهای حافظه مشخص می‌کند.

    داخل گروه:

        !حافظه 8000
            -> گروه فعلی

        !حافظه 8000 -100123
            -> گروه ریموت

    داخل PV:

        !حافظه 8000 -100123
            -> گروه ریموت

        !حافظه 8000
            -> خطا، چون مقصد مشخص نشده

    مقدار bool مشخص می‌کند که مقصد ریموت بوده یا نه.
    """

    raw = (
        event.args_text or ""
    ).strip()

    target_group, clean_args = (
        _extract_optional_group_target(
            raw
        )
    )

    # مقصد ریموت مشخص شده.
    if target_group is not None:
        return (
            target_group,
            clean_args,
            True,
        )

    # داخل گروه و بدون مقصد ریموت:
    # مقصد = گروه فعلی
    if event.is_group:
        return (
            event.chat_id,
            clean_args,
            False,
        )

    # داخل PV بدون مقصد ریموت:
    # مقصد نامشخص است.
    return (
        None,
        clean_args,
        False,
    )


def mask_secret(secret):
    if not secret:
        return "تنظیم نشده"

    if len(secret) <= 8:
        return "••••••••"

    return (
        f"{secret[:4]}••••{secret[-4:]}"
    )


# =========================================================
# API KEY MANAGEMENT
# =========================================================


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
    args = (
        event.args_text or ""
    ).strip().split()

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
    name = (
        event.args_text or ""
    ).strip()

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
    name = (
        event.args_text or ""
    ).strip()

    if not name:
        await event.reply(
            "مثال: !کلید مدل ها zai"
        )
        return

    api_key = await self.api_keys.get(
        name
    )

    if api_key is None:
        await event.reply(
            f"❌ API Key «{name}» پیدا نشد."
        )
        return

    try:
        models = (
            await self.gateway.list_remote_models(
                api_key
            )
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
    name="کلید مدل ها پینگ",
    permission="owner",
    chat_type="all",
    description="مدل‌های API را همزمان Ping می‌کند.",
)
async def api_key_models_ping(
    self,
    event,
):
    name = (
        event.args_text or ""
    ).strip()

    if not name:
        await event.reply(
            "مثال: !کلید مدل ها پینگ zai"
        )
        return

    api_key = await self.api_keys.get(
        name
    )

    if api_key is None:
        await event.reply(
            f"❌ API Key «{name}» پیدا نشد."
        )
        return

    try:
        models = (
            await self.gateway.list_remote_models(
                api_key
            )
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
        results = (
            await self.gateway.ping_remote_models(
                api_key,
                models,
            )
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

    for (
        model_id,
        ok,
        latency,
        error,
    ) in results:

        if ok:
            lines.append(
                f"✅ `{model_id}` — "
                f"{latency:.0f}ms"
            )

        else:
            error = (
                str(error)
                .replace("\n", " ")
                .strip()
            )

            if len(error) > 100:
                error = error[:97] + "..."

            lines.append(
                f"❌ `{model_id}` — "
                f"{latency:.0f}ms — {error}"
            )

    chunk_size = 3000

    chunks = []
    current = ""

    for line in lines:
        if (
            len(current)
            + len(line)
            + 1
            > chunk_size
        ):
            if current:
                chunks.append(
                    current
                )

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


# =========================================================
# MEMORY MANAGEMENT
# =========================================================


@command(
    name="حافظه پاک",
    permission="owner",
    chat_type="all",
    description="تمام حافظه و خلاصه‌ی بوبی در این گروه را پاک می‌کند.",
)
async def clear_memory(
    self,
    event: events.NewMessage.Event,
) -> None:

    (
        target_group,
        value,
        remote,
    ) = _resolve_memory_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!حافظه پاک -10024473944"
        )
        return

    # برای این کامند نباید آرگومان دیگری وجود داشته باشد.
    if value:
        await event.reply(
            "❌ استفاده نادرست.\n"
            "مثال:\n"
            "!حافظه پاک -10024473944"
        )
        return

    try:
        await self.memory.store.clear_group(
            target_group
        )

    except Exception as exc:
        print(
            f"❌ خطا در پاک کردن حافظه گروه "
            f"{target_group}: {exc}"
        )

        await event.reply(
            "❌ پاک کردن حافظه ناموفق بود."
        )
        return

    await event.reply(
        f"🧠 حافظه‌ی بوبی در گروه "
        f"`{target_group}` کامل پاک شد."
    )


@command(
    name="حافظه",
    permission="owner",
    chat_type="all",
    description="حداکثر تعداد توکن حافظه مکالمه این گروه را تنظیم می‌کند.",
)
async def memory_limit(
    self,
    event: events.NewMessage.Event,
) -> None:

    (
        target_group,
        value,
        remote,
    ) = _resolve_memory_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!حافظه 8000 -10024473944"
        )
        return

    if not value:
        limit = (
            await self.memory.settings.get_token_limit(
                target_group
            )
        )

        await event.reply(
            f"🧠 سقف حافظه گروه "
            f"`{target_group}`: "
            f"{limit:,} توکن"
        )
        return

    if not value.isdigit():
        await event.reply(
            "مثال:\n"
            "!حافظه 8000\n"
            "یا:\n"
            "!حافظه 8000 -10024473944"
        )
        return

    limit = int(value)

    if limit < 100:
        await event.reply(
            "❌ حداقل مقدار حافظه 100 توکن است."
        )
        return

    await self.memory.settings.set_token_limit(
        target_group,
        limit,
    )

    await event.reply(
        f"✅ سقف حافظه گروه "
        f"`{target_group}` روی "
        f"{limit:,} توکن تنظیم شد."
    )


@command(
    name="حافظه پیام",
    permission="owner",
    chat_type="all",
    description="حداکثر تعداد پیام ذخیره‌شده حافظه این گروه را تنظیم می‌کند.",
)
async def memory_message_limit(
    self,
    event: events.NewMessage.Event,
) -> None:

    (
        target_group,
        value,
        remote,
    ) = _resolve_memory_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!حافظه پیام 500 -10024473944"
        )
        return

    if not value:
        limit = (
            await self.memory.settings.get_message_limit(
                target_group
            )
        )

        await event.reply(
            f"🗃️ سقف پیام‌های حافظه گروه "
            f"`{target_group}`: "
            f"{limit:,} پیام"
        )
        return

    if not value.isdigit():
        await event.reply(
            "مثال:\n"
            "!حافظه پیام 500\n"
            "یا:\n"
            "!حافظه پیام 500 -10024473944"
        )
        return

    limit = int(value)

    if limit < 10:
        await event.reply(
            "❌ حداقل تعداد پیام 10 است."
        )
        return

    await self.memory.settings.set_message_limit(
        target_group,
        limit,
    )

    await self.memory.trim(
        target_group
    )

    await event.reply(
        f"✅ سقف پیام‌های حافظه گروه "
        f"`{target_group}` روی "
        f"{limit:,} پیام تنظیم شد."
    )


# =========================================================
# MODEL MANAGEMENT
# =========================================================


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
            "!مدل افزودن <نام_مدل> <provider> "
            "<model_id> <API_KEY> [BASE_URL]"
        )
        return

    if len(args) == 3:
        model_name = args[0]
        api_key_name = args[1]
        model_id = args[2]

        api_key_data = (
            await self.api_keys.get(
                api_key_name
            )
        )

        if api_key_data is None:
            await event.reply(
                f"❌ API Key "
                f"«{api_key_name}» پیدا نشد."
            )
            return

        provider = api_key_data[
            "provider"
        ]

        api_key = api_key_data[
            "api_key"
        ]

        base_url = api_key_data[
            "base_url"
        ]

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

    if len(args) < 4:
        await event.reply(
            "❌ پارامترهای کافی وارد نشده.\n\n"
            "استفاده از API Key ذخیره‌شده:\n"
            "!مدل افزودن <نام_مدل> "
            "<نام_API_Key> <model_id>\n\n"
            "یا اطلاعات کامل:\n"
            "!مدل افزودن <نام_مدل> "
            "<provider> <model_id> "
            "<API_KEY> [BASE_URL]"
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


@command(
    name="مدل ها",
    permission="owner",
    chat_type="all",
    description="لیست مدل ها",
)
async def list_models(
    self,
    event,
):
    models = await self.models.get_all()

    if not models:
        await event.reply(
            "📦 هیچ مدلی ثبت نشده."
        )
        return

    await event.reply(
        "🤖 مدل ها:\n\n"
        + "\n".join(
            (
                f"{'🟢' if m['is_active'] else '⚪'} "
                f"{m['name']} — "
                f"{m['provider']}/{m['model_id']}"
            )
            for m in models
        )
    )


@command(
    name="مدل فعال",
    permission="owner",
    chat_type="all",
    description="فعال کردن یا دیدن مدل فعال",
)
async def activate_model(
    self,
    event,
):
    name = (
        event.args_text or ""
    ).strip()

    if not name:
        model = (
            await self.models.get_active()
        )

        await event.reply(
            "ℹ️ مدل فعالی وجود ندارد."
            if not model
            else
            f"🟢 {model['name']} — "
            f"{model['provider']}/"
            f"{model['model_id']}"
        )
        return

    if not await self.models.set_active(
        name
    ):
        await event.reply(
            f"❌ مدل «{name}» پیدا نشد."
        )
        return

    await event.reply(
        f"✅ مدل «{name}» فعال شد."
    )


@command(
    name="مدل حذف",
    permission="owner",
    chat_type="all",
    description="حذف مدل",
)
async def delete_model(
    self,
    event,
):
    name = (
        event.args_text or ""
    ).strip()

    if not name:
        await event.reply(
            "مثال: !مدل حذف gpt"
        )
        return

    if not await self.models.delete(
        name
    ):
        await event.reply(
            f"❌ مدل «{name}» پیدا نشد."
        )
        return

    await event.reply(
        f"✅ مدل «{name}» حذف شد."
    )


@command(
    name="مدل اطلاعات",
    permission="owner",
    chat_type="all",
    description="جزئیات مدل",
)
async def model_info(
    self,
    event,
):
    name = (
        event.args_text or ""
    ).strip()

    model = await self.models.get(
        name
    )

    if not model:
        await event.reply(
            "❌ مدل پیدا نشد."
        )
        return

    await event.reply(
        f"🤖 {model['name']}\n"
        f"Provider: {model['provider']}\n"
        f"Model ID: {model['model_id']}\n"
        f"Base URL: "
        f"{model['base_url'] or 'پیش فرض'}\n"
        f"API Key: "
        f"{mask_secret(model['api_key'])}\n"
        f"Active: "
        f"{'بله' if model['is_active'] else 'خیر'}"
    )


@command(
    name="مدل کلید",
    permission="owner",
    chat_type="all",
    description="تغییر API Key",
)
async def update_model_key(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).split()

    if len(args) != 2:
        await event.reply(
            "مثال: !مدل کلید gpt NEW_API_KEY"
        )
        return

    success = await self.models.update_api_key(
        args[0],
        None
        if args[1] == "-"
        else args[1],
    )

    if not success:
        await event.reply(
            "❌ مدل پیدا نشد."
        )
        return

    try:
        await event.delete()

    except Exception:
        pass

    await event.reply(
        "✅ API Key بروزرسانی شد."
    )


@command(
    name="مدل پینگ",
    permission="owner",
    chat_type="all",
    description="تست مدل ها",
)
async def ping_models(
    self,
    event,
):
    target = (
        event.args_text or ""
    ).strip()

    if target:
        models = [
            await self.models.get(target)
        ]

    else:
        models = (
            await self.models.get_all()
        )

    models = [
        model
        for model in models
        if model
    ]

    if not models:
        await event.reply(
            "📡 مدلی برای Ping وجود ندارد."
        )
        return

    lines = [
        "📡 نتیجه Ping:"
    ]

    for model in models:
        (
            ok,
            latency,
            error,
        ) = await self.gateway.ping(
            model
        )

        line = (
            f"{'✅' if ok else '❌'} "
            f"{model['name']} — "
            f"{latency:.0f}ms"
        )

        if not ok:
            line += (
                " — "
                + error[:120].replace(
                    "\n",
                    " ",
                )
            )

        lines.append(line)

    await event.reply(
        "\n".join(lines)
    )


# =========================================================
# PROMPT / TRIGGER
# =========================================================


@command(
    name="پرامپت",
    permission="owner",
    chat_type="all",
    description="دیدن System Prompt",
)
async def show_prompt(
    self,
    event,
):
    await event.reply(
        "🧠 System Prompt:\n\n"
        + await self.groups.get_system_prompt(
            event.chat_id
        )
    )


@command(
    name="پرامپت تنظیم",
    permission="owner",
    chat_type="all",
    description="تغییر System Prompt",
)
async def set_prompt(
    self,
    event,
):
    prompt = (
        event.args_text or ""
    ).strip()

    if not prompt:
        await event.reply(
            "مثال: !پرامپت تنظیم تو بوبی هستی"
        )
        return

    await self.groups.set_system_prompt(
        event.chat_id,
        prompt,
    )

    await event.reply(
        "✅ System Prompt تغییر کرد."
    )


@command(
    name="پرامپت ریست",
    permission="owner",
    chat_type="all",
    description="بازگردانی System Prompt",
)
async def reset_prompt(
    self,
    event,
):
    await self.groups.reset_system_prompt(
        event.chat_id
    )

    await event.reply(
        "✅ System Prompt ریست شد."
    )


@command(
    name="نام ربات",
    permission="owner",
    chat_type="all",
    description="دیدن یا تغییر Trigger",
)
async def bot_name(
    self,
    event,
):
    value = (
        event.args_text or ""
    ).strip()

    if not value:
        await event.reply(
            "🏷️ Trigger: "
            + await self.groups.get_trigger(
                event.chat_id,
                self.default_trigger,
            )
        )
        return

    await self.groups.set_trigger(
        event.chat_id,
        value,
    )

    await event.reply(
        f"✅ Trigger شد: {value}"
    )


# =========================================================
# TIMELINE SETTINGS
# =========================================================


@command(
    name="تایم لاین",
    permission="owner",
    chat_type="all",
    description="تنظیم سراسری Timeline هوش مصنوعی",
)
async def timeline_toggle(
    self,
    event,
):
    raw = (
        event.args_text or ""
    ).strip()

    if not raw:
        status = (
            "🟢 فعال"
            if self.timeline_enabled
            else "🔴 خاموش"
        )

        await event.reply(
            f"🧭 وضعیت Timeline سراسری: {status}\n"
            f"📦 سقف هر گروه: "
            f"{self.timeline_limit} پیام\n\n"
            "روشن کردن:\n"
            "!تایم لاین روشن 200\n\n"
            "خاموش کردن:\n"
            "!تایم لاین خاموش"
        )
        return

    parts = raw.split()

    action = parts[0].lower()

    if action in {
        "روشن",
        "on",
        "1",
        "فعال",
    }:
        limit = (
            self.timeline_limit
        )

        if len(parts) >= 2:
            if not parts[1].isdigit():
                await event.reply(
                    "❌ مقدار تعداد پیام نامعتبر است.\n"
                    "مثال:\n"
                    "!تایم لاین روشن 200"
                )
                return

            limit = int(parts[1])

        if limit < 10:
            await event.reply(
                "❌ حداقل تعداد پیام 10 است."
            )
            return

        if (
            limit
            > self.memory.MAX_TIMELINE_MESSAGES
        ):
            await event.reply(
                f"❌ حداکثر تعداد پیام "
                f"{self.memory.MAX_TIMELINE_MESSAGES} است."
            )
            return

        self.timeline_enabled = True
        self.timeline_limit = limit

        await self.store.timeline.set(
            enabled=True,
            message_limit=limit,
        )

        await event.reply(
            "✅ Timeline سراسری روشن شد.\n"
            f"📦 سقف هر گروه: {limit} پیام\n"
            "💾 این تنظیم در دیتابیس ذخیره شد."
        )
        return

    if action in {
        "خاموش",
        "off",
        "0",
        "غیرفعال",
    }:
        self.timeline_enabled = False

        await self.store.timeline.set(
            enabled=False,
            message_limit=self.timeline_limit,
        )

        self.memory.clear_all_timelines()

        await event.reply(
            "🛑 Timeline سراسری خاموش شد.\n"
            "🧹 Timelineهای RAM پاک شدند.\n"
            "💾 وضعیت خاموش در دیتابیس ذخیره شد."
        )
        return

    await event.reply(
        "❌ استفاده نادرست.\n\n"
        "برای روشن کردن:\n"
        "!تایم لاین روشن 200\n\n"
        "برای خاموش کردن:\n"
        "!تایم لاین خاموش"
    )


# =========================================================
# TIMELINE DISPLAY
# =========================================================


@command(
    name="نمایش تایم لاین",
    permission="owner",
    chat_type="all",
    description="Timeline گروه را نمایش می‌دهد.",
)
async def show_timeline(
    self,
    event,
) -> None:
    raw = (
        event.args_text or ""
    ).strip()

    (
        target_group,
        remaining,
    ) = _extract_optional_group_target(
        raw
    )

    # اگر آرگومان دیگری باقی مانده،
    # syntax نامعتبر است.
    if remaining:
        await event.reply(
            "❌ استفاده نادرست.\n"
            "داخل گروه:\n"
            "!نمایش تایم لاین\n\n"
            "برای گروه دیگر:\n"
            "!نمایش تایم لاین -10024473944"
        )
        return

    # -------------------------------------------------
    # Remote
    # -------------------------------------------------

    if target_group is not None:
        if not self.timeline_enabled:
            await event.reply(
                "🛑 Timeline سراسری خاموش است."
            )
            return

        context = (
            self.memory.get_timeline_context(
                target_group
            )
        )

        if not context:
            await event.reply(
                "❌ Timeline مورد نظر لود نشده!"
            )
            return

    # -------------------------------------------------
    # Local
    # -------------------------------------------------

    else:
        if not event.is_group:
            await event.reply(
                "❌ در PV باید شناسه گروه را وارد کنید.\n"
                "مثال:\n"
                "!نمایش تایم لاین -10024473944"
            )
            return

        if not self.timeline_enabled:
            await event.reply(
                "🛑 Timeline سراسری خاموش است."
            )
            return

        await self.memory.ensure_timeline(
            self.client,
            event.chat_id,
            self.timeline_limit,
        )

        context = (
            self.memory.get_timeline_context(
                event.chat_id
            )
        )

        if not context:
            await event.reply(
                "🧭 هنوز پیام قابل‌نمایشی "
                "در Timeline این گروه وجود ندارد."
            )
            return

    # -------------------------------------------------
    # ارسال Timeline
    # -------------------------------------------------

    lines = context.split("\n")

    chunk_size = 3000

    chunks = []
    current = ""

    for line in lines:
        if (
            len(current)
            + len(line)
            + 1
            > chunk_size
        ):
            if current:
                chunks.append(
                    current
                )

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
                f"❌ خطا در ارسال Timeline: {exc}"
            )
            break


@command(
    name="پاک تایم لاین",
    permission="owner",
    chat_type="all",
    description="Timeline گروه را از RAM پاک می‌کند.",
)
async def clear_timeline_command(
    self,
    event,
) -> None:
    raw = (
        event.args_text or ""
    ).strip()

    (
        target_group,
        remaining,
    ) = _extract_optional_group_target(
        raw
    )

    if remaining:
        await event.reply(
            "❌ استفاده نادرست.\n"
            "داخل گروه:\n"
            "!پاک تایم لاین\n\n"
            "برای گروه دیگر:\n"
            "!پاک تایم لاین -10024473944"
        )
        return

    # -------------------------------------------------
    # Remote
    # -------------------------------------------------

    if target_group is not None:
        if not self.memory.has_timeline(
            target_group
        ):
            await event.reply(
                "❌ Timeline مورد نظر لود نشده!"
            )
            return

        self.memory.clear_timeline(
            target_group
        )

        await event.reply(
            "🧹 Timeline گروه مورد نظر "
            "از RAM پاک شد."
        )
        return

    # -------------------------------------------------
    # Local
    # -------------------------------------------------

    if not event.is_group:
        await event.reply(
            "❌ در PV باید شناسه گروه را وارد کنید.\n"
            "مثال:\n"
            "!پاک تایم لاین -10024473944"
        )
        return

    if not self.memory.has_timeline(
        event.chat_id
    ):
        await event.reply(
            "❌ Timeline این گروه لود نشده!"
        )
        return

    self.memory.clear_timeline(
        event.chat_id
    )

    await event.reply(
        "🧹 Timeline این گروه از RAM پاک شد."
    )


@command(
    name="تایم لاین های RAM",
    permission="owner",
    chat_type="all",
    description="Timelineهای موجود در RAM را نشان می‌دهد.",
)
async def show_cached_timelines(
    self,
    event,
):
    timelines = (
        self.memory.get_cached_timeline_stats()
    )

    if not timelines:
        await event.reply(
            "🧭 هیچ Timelineای در RAM "
            "کش نشده است."
        )
        return

    lines = [
        "🧭 Timelineهای موجود در RAM:",
        "",
    ]

    total_messages = 0

    for (
        index,
        (
            group_id,
            message_count,
        ),
    ) in enumerate(
        timelines,
        start=1,
    ):
        lines.append(
            f"{index}. گروه `{group_id}` — "
            f"{message_count} پیام"
        )

        total_messages += message_count

    lines.extend(
        [
            "",
            f"📦 تعداد Timelineها: "
            f"{len(timelines)}",
            f"💾 مجموع پیام‌های کش‌شده: "
            f"{total_messages}",
        ]
    )

    await event.reply(
        "\n".join(lines)
    )


# =========================================================
# TIMELINE LOADER
# =========================================================


@command(
    name="تاریخچه",
    permission="owner",
    chat_type="all",
    description="تعداد مشخصی از پیام‌های اخیر را در Timeline آماده می‌کند.",
)
async def load_timeline(
    self,
    event,
):
    args_text = (
        event.args_text or ""
    ).strip()

    (
        target_group,
        args_text,
    ) = _extract_optional_group_target(
        args_text
    )

    # -------------------------------------------------
    # اگر مقصد مشخص نشده:
    # داخل گروه = گروه فعلی
    # PV = خطا
    # -------------------------------------------------

    if target_group is None:
        if event.is_group:
            target_group = event.chat_id

        else:
            await event.reply(
                "❌ در PV باید شناسه گروه را وارد کنید.\n"
                "مثال:\n"
                "!تاریخچه 200 -10024473944"
            )
            return

    # -------------------------------------------------
    # فعال بودن Timeline
    # -------------------------------------------------

    if not self.timeline_enabled:
        await event.reply(
            "🛑 Timeline در حال حاضر خاموش است."
        )
        return

    # -------------------------------------------------
    # تعداد پیام
    # -------------------------------------------------

    if not args_text.isdigit():
        await event.reply(
            "مثال:\n"
            "!تاریخچه 200\n"
            "یا:\n"
            "!تاریخچه 200 -10024473944"
        )
        return

    limit = int(args_text)

    if limit < 10:
        await event.reply(
            "❌ حداقل تعداد پیام 10 است."
        )
        return

    if (
        limit
        > self.memory.MAX_TIMELINE_MESSAGES
    ):
        await event.reply(
            f"❌ حداکثر تعداد پیام "
            f"{self.memory.MAX_TIMELINE_MESSAGES} است."
        )
        return

    # -------------------------------------------------
    # Load
    # -------------------------------------------------

    try:
        count = (
            await self.memory.load_timeline(
                self.client,
                target_group,
                limit,
            )
        )

    except Exception as exc:
        print(
            "❌ خطا در بارگذاری Timeline:",
            exc,
        )

        await event.reply(
            "❌ نتونستم تاریخچه گروه "
            "را بارگذاری کنم."
        )
        return

    await event.reply(
        f"🧭 Timeline آماده شد.\n"
        f"📦 {count} پیام در RAM نگه داشته می‌شود.\n\n"
        f"گروه هدف: {target_group}"
    )


# =========================================================
# TIMELINE EVENTS
# =========================================================


@on_event(events.MessageDeleted)
async def on_timeline_message_deleted(
    self,
    event,
):
    try:
        if not self.timeline_enabled:
            return

        deleted_ids = getattr(
            event,
            "deleted_ids",
            None,
        )

        if not deleted_ids:
            return

        group_id = getattr(
            event,
            "chat_id",
            None,
        )

        for raw_message_id in deleted_ids:
            try:
                message_id = int(
                    raw_message_id
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            self.memory.mark_deleted_message(
                message_id=message_id,
                group_id=group_id,
                reason="این پیام حذف شده است",
            )

    except Exception:
        traceback.print_exc()


# =========================================================
# AI MESSAGE HANDLER
# =========================================================
# =========================================================
# AI MESSAGE HANDLER
# =========================================================

@on_event(
    events.NewMessage(
        incoming=True
    )
)
async def on_message(
    self,
    event,
):
    try:
        # -------------------------------------------------
        # فقط گروه‌ها
        # -------------------------------------------------

        if not event.is_group:
            return

        # -------------------------------------------------
        # متن پیام
        # -------------------------------------------------

        text = (
            event.raw_text or ""
        ).strip()

        if (
            not text
            or text.startswith("!")
        ):
            return

        if event.sender_id is None:
            return

        # -------------------------------------------------
        # Trigger detection
        # -------------------------------------------------

        trigger = (
            await self.groups.get_trigger(
                event.chat_id,
                self.default_trigger,
            )
        )

        trigger_text = extract_trigger_text(
            text,
            trigger,
        )

        if trigger_text is None:
            return

        # -------------------------------------------------
        # DEBUG
        # -------------------------------------------------

        print(
            f"✅ BOOBY TRIGGERED | "
            f"group={event.chat_id} | "
            f"trigger={trigger!r} | "
            f"trigger_text={trigger_text!r} | "
            f"text={text!r}"
        )

        # -------------------------------------------------
        # Timeline
        # -------------------------------------------------

        if self.timeline_enabled:
            try:
                await self.memory.ensure_timeline(
                    self.client,
                    event.chat_id,
                    self.timeline_limit,
                )

                await self.memory.record_event(
                    event
                )

            except Exception:
                traceback.print_exc()

        # -------------------------------------------------
        # پیام فعلی برای Memory
        # -------------------------------------------------

        prompt_text = text

        try:
            sender = (
                await event.get_sender()
            )

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
                or str(
                    event.sender_id
                )
            )

        except Exception:
            name = str(
                event.sender_id
            )

        message_id = (
            self.memory._extract_message_id(
                event
            )
        )

        user_content = (
            self.memory.format_user_message(
                name,
                int(event.sender_id),
                message_id,
                prompt_text,
            )
        )

        await self.memory.store.add_message(
            event.chat_id,
            "user",
            user_content,
            event.sender_id,
        )

        await self.memory.maybe_trim(
            event.chat_id
        )

        # -------------------------------------------------
        # Build Context
        # -------------------------------------------------

        context = (
            await self.memory.build_context(
                event.chat_id,
                await self.groups.get_system_prompt(
                    event.chat_id
                ),
                self.gateway,
            )
        )

        # -------------------------------------------------
        # DEBUG: قبل از درخواست API
        # -------------------------------------------------

        context_chars = sum(
            len(
                str(
                    message.get(
                        "content",
                        "",
                    )
                )
            )
            for message in context
        )

        print(
            f"📡 BOOBY AI REQUEST | "
            f"group={event.chat_id} | "
            f"messages={len(context)} | "
            f"chars={context_chars}"
        )

        # -------------------------------------------------
        # درخواست به مدل
        # -------------------------------------------------

        answer = await self.gateway.chat(
            context
        )

        # -------------------------------------------------
        # DEBUG: پاسخ دریافت شد
        # -------------------------------------------------

        print(
            f"✅ BOOBY AI RESPONSE | "
            f"group={event.chat_id} | "
            f"chars={len(answer)}"
        )

        await self.memory.store.add_message(
            event.chat_id,
            "assistant",
            answer,
        )

        # -------------------------------------------------
        # ارسال پاسخ
        # -------------------------------------------------

        sent = await event.reply(
            answer[:4000]
        )

        # -------------------------------------------------
        # Timeline: پاسخ بوبی
        # -------------------------------------------------

        if self.timeline_enabled:
            try:
                if sent is not None:
                    await self.memory.record_generated_message(
                        event.chat_id,
                        sent,
                    )

            except Exception:
                traceback.print_exc()

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
                "❌ هنگام پردازش پیام "
                "مشکلی پیش آمد."
            )

        except Exception:
            pass
# =========================================================
# MODERATION -> TIMELINE
# =========================================================


@on_bus_event("violation")
async def on_violation_deleted(
    self,
    event,
    group_id: int,
    user_id: int,
    reason: str,
    message_ids: list[int] | None = None,
) -> None:

    if not self.timeline_enabled:
        return

    ids = message_ids

    if not ids:
        message_id = (
            self.memory._extract_message_id(
                event
            )
        )

        if message_id is None:
            return

        ids = [
            message_id
        ]

    for message_id in ids:
        self.memory.mark_deleted(
            group_id,
            event,
            reason,
            message_id=message_id,
        )


@on_bus_event(
    "timeline_system_message"
)
async def on_timeline_system_message(
    self,
    group_id: int,
    message,
) -> None:

    if not self.timeline_enabled:
        return

    if message is None:
        return

    try:
        await self.memory.ensure_timeline(
            self.client,
            group_id,
            self.timeline_limit,
        )

        await self.memory.record_generated_message(
            group_id,
            message,
            message_type="moderation_event",
        )

    except Exception:
        traceback.print_exc()