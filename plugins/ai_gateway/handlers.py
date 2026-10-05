from splusthon import events

from core.decorators import command, on_bus_event, on_event

from .gateway import AIGatewayError
from .trigger import extract_trigger_text
from .store import AIModelStatisticsStore
from plugins.ai_gateway.utils import score_emoji
import traceback
import time

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













@command(
    name="استریمر هوش مصنوعی",
    permission="owner",
    chat_type="all",
    description="گروه فعلی را به مقصد Live Telemetry هوش مصنوعی متصل می‌کند.",
)
async def ai_telemetry_streamer(
    self,
    event,
) -> None:

    action = (
        event.args_text or ""
    ).strip()

    # -------------------------------------------------
    # خاموش
    # -------------------------------------------------

    if action == "خاموش":

        await self.store.telemetry.clear_target()

        self.telemetry.clear_target()

        await event.reply(
            "🛑 Live Telemetry هوش مصنوعی خاموش شد."
        )

        return

    # -------------------------------------------------
    # وضعیت
    # -------------------------------------------------

    if action == "وضعیت":

        settings = (
            await self.store.telemetry.get()
        )

        if (
            not settings["enabled"]
            or settings["target_group_id"]
            is None
        ):
            await event.reply(
                "📡 Live Telemetry هوش مصنوعی خاموش است."
            )

            return

        await event.reply(
            "📡 Live Telemetry هوش مصنوعی فعال است.\n\n"
            f"🏠 Group ID: "
            f"{settings['target_group_id']}"
        )

        return

    # -------------------------------------------------
    # آرگومان نامعتبر
    # -------------------------------------------------

    if action:

        await event.reply(
            "❌ استفاده نادرست.\n\n"
            "!استریمر هوش مصنوعی\n"
            "!استریمر هوش مصنوعی وضعیت\n"
            "!استریمر هوش مصنوعی خاموش"
        )

        return

    # -------------------------------------------------
    # فعال‌سازی در گروه فعلی
    # -------------------------------------------------

    if not event.is_group:

        await event.reply(
            "❌ این کامند باید داخل گروه Telemetry اجرا شود."
        )

        return

    group_id = int(
        event.chat_id
    )

    await self.store.telemetry.set_target(
        group_id
    )

    self.telemetry.set_target(
        group_id
    )

    await event.reply(
        "✅ Live Telemetry هوش مصنوعی فعال شد.\n\n"
        f"🏠 Group ID: {group_id}\n\n"
        "از این به بعد اطلاعات اجرای بوبی "
        "در همین گروه stream می‌شود."
    )



# =========================================================
# PROVIDER MANAGEMENT
# =========================================================


@command(
    name="ارائه دهنده افزودن",
    permission="owner",
    chat_type="all",
    description="یک AI Provider جدید اضافه می‌کند.",
)
async def add_provider(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) not in {3, 4}:
        await event.reply(
            "❌ استفاده نادرست.\n\n"
            "فرمت:\n"
            "!ارائه دهنده افزودن "
            "<نام> <provider> <base_url> [models_url]\n\n"
            "مثال:\n"
            "!ارائه دهنده افزودن gemini "
            "openai https://example.com/v1"
        )
        return

    name = args[0]
    provider = args[1]
    base_url = args[2]

    models_url = (
        args[3]
        if len(args) == 4
        else None
    )

    try:
        provider_id = (
            await self.providers.add(
                name=name,
                provider=provider,
                base_url=base_url,
                models_url=models_url,
            )
        )

    except Exception as exc:
        await event.reply(
            f"❌ افزودن Provider ناموفق بود:\n{exc}"
        )
        return

    try:
        await event.delete()
    except Exception:
        pass

    await event.reply(
        f"✅ Provider «{name}» ساخته شد.\n\n"
        f"🆔 ID: {provider_id}\n"
        f"🔌 LiteLLM Provider: {provider}\n"
        f"🌐 Base URL: {base_url}"
    )


@command(
    name="ارائه دهنده ها",
    permission="owner",
    chat_type="all",
    description="لیست AI Providerها را نشان می‌دهد.",
)
async def list_providers(
    self,
    event,
):
    providers = (
        await self.providers.get_all()
    )

    if not providers:
        await event.reply(
            "📦 هیچ AI Provider ثبت نشده است."
        )
        return

    lines = []

    for provider in providers:

        keys = (
            await self.providers.get_api_keys(
                provider["id"]
            )
        )

        models = [
            model
            for model in (
                await self.models.get_all()
            )
            if int(model["provider_id"])
            == int(provider["id"])
        ]

        available_count = sum(
            1
            for key in keys
            if key["status"] == "AVAILABLE"
        )

        lines.append(
            f"🔌 `{provider['name']}`\n"
            f"   LiteLLM: `{provider['provider']}`\n"
            f"   Models: {len(models)}\n"
            f"   Keys: {len(keys)} "
            f"(available: {available_count})"
        )

    await event.reply(
        "🔌 AI Providerها:\n\n"
        + "\n\n".join(lines)
    )


@command(
    name="ارائه دهنده اطلاعات",
    permission="owner",
    chat_type="all",
    description="اطلاعات کامل یک Provider را نشان می‌دهد.",
)
async def provider_info(
    self,
    event,
):
    name = (
        event.args_text or ""
    ).strip()

    if not name:
        await event.reply(
            "مثال: !ارائه دهنده اطلاعات gemini"
        )
        return

    provider = await self.providers.get(
        name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{name}» پیدا نشد."
        )
        return

    keys = (
        await self.providers.get_api_keys(
            provider["id"]
        )
    )

    models = [
        model
        for model in (
            await self.models.get_all()
        )
        if int(model["provider_id"])
        == int(provider["id"])
    ]

    key_lines = []

    for key in keys:

        state = (
            "🟢 فعال"
            if key["is_active"]
            else "⚪ عادی"
        )

        key_lines.append(
            f"{state} "
            f"#{key['key_number']} — "
            f"{mask_secret(key['api_key'])} "
            f"[{key['status']}]"
        )

    model_lines = [
        (
            f"🤖 `{model['name']}` — "
            f"`{model['model_id']}`"
        )
        for model in models
    ]

    await event.reply(
        f"🔌 Provider: `{provider['name']}`\n"
        f"🔧 LiteLLM Provider: `{provider['provider']}`\n"
        f"🌐 Base URL: "
        f"{provider['base_url'] or 'پیش‌فرض'}\n"
        f"📦 Models URL: "
        f"{provider['models_url'] or 'Base URL + /models'}\n\n"

        f"🔑 API Key Pool ({len(keys)}):\n"
        + (
            "\n".join(key_lines)
            if key_lines
            else "هیچ Key ثبت نشده."
        )
        + "\n\n"

        f"🤖 Models ({len(models)}):\n"
        + (
            "\n".join(model_lines)
            if model_lines
            else "هیچ Model ثبت نشده."
        )
    )


@command(
    name="ارائه دهنده تنظیم",
    permission="owner",
    chat_type="all",
    description="تنظیمات اتصال یک Provider را تغییر می‌دهد.",
)
async def update_provider(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) not in {3, 4}:
        await event.reply(
            "❌ استفاده نادرست.\n\n"
            "فرمت:\n"
            "!ارائه دهنده تنظیم "
            "<نام> <provider> <base_url> [models_url]"
        )
        return

    name = args[0]
    provider = args[1]
    base_url = args[2]

    models_url = (
        args[3]
        if len(args) == 4
        else None
    )

    try:
        success = await self.providers.update(
            name=name,
            provider=provider,
            base_url=base_url,
            models_url=models_url,
        )

    except Exception as exc:
        await event.reply(
            f"❌ بروزرسانی Provider ناموفق بود:\n{exc}"
        )
        return

    if not success:
        await event.reply(
            f"❌ Provider «{name}» پیدا نشد."
        )
        return

    await event.reply(
        f"✅ تنظیمات Provider «{name}» بروزرسانی شد."
    )


@command(
    name="ارائه دهنده حذف",
    permission="owner",
    chat_type="all",
    description="یک AI Provider را حذف می‌کند.",
)
async def delete_provider(
    self,
    event,
):
    name = (
        event.args_text or ""
    ).strip()

    if not name:
        await event.reply(
            "مثال: !ارائه دهنده حذف gemini"
        )
        return

    try:
        deleted = await self.providers.delete(
            name
        )

    except Exception as exc:
        await event.reply(
            f"❌ حذف Provider ناموفق بود:\n{exc}"
        )
        return

    if not deleted:
        await event.reply(
            f"❌ Provider «{name}» پیدا نشد."
        )
        return

    await event.reply(
        f"✅ Provider «{name}» حذف شد."
    )


# =========================================================
# PROVIDER API KEY POOL
# =========================================================


@command(
    name="ارائه دهنده کلید افزودن",
    permission="owner",
    chat_type="all",
    description="یک API Key به Pool یک Provider اضافه می‌کند.",
)
async def add_provider_api_key(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) != 2:
        await event.reply(
            "مثال:\n"
            "!ارائه دهنده کلید افزودن gemini API_KEY"
        )
        return

    provider_name = args[0]
    api_key = args[1]

    provider = await self.providers.get(
        provider_name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{provider_name}» پیدا نشد."
        )
        return

    try:
        key_number = (
            await self.providers.add_api_key(
                provider["id"],
                api_key,
            )
        )

    except Exception as exc:
        await event.reply(
            f"❌ افزودن API Key ناموفق بود:\n{exc}"
        )
        return

    if key_number == 0:
        await event.reply(
            "⚠️ این API Key قبلاً در Pool همین Provider وجود دارد."
        )
        return

    try:
        await event.delete()
    except Exception:
        pass

    await event.reply(
        f"✅ API Key شماره #{key_number} "
        f"به Pool Provider «{provider_name}» اضافه شد."
    )


@command(
    name="ارائه دهنده کلید ها",
    permission="owner",
    chat_type="all",
    description="Pool کلیدهای یک Provider را نشان می‌دهد.",
)
async def list_provider_api_keys(
    self,
    event,
):
    provider_name = (
        event.args_text or ""
    ).strip()

    if not provider_name:
        await event.reply(
            "مثال: !ارائه دهنده کلید ها gemini"
        )
        return

    provider = await self.providers.get(
        provider_name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{provider_name}» پیدا نشد."
        )
        return

    keys = (
        await self.providers.get_api_keys(
            provider["id"]
        )
    )

    if not keys:
        await event.reply(
            f"🔑 Pool Provider «{provider_name}» خالی است."
        )
        return

    lines = []

    for key in keys:

        state = (
            "🟢 ACTIVE"
            if key["is_active"]
            else "⚪"
        )

        lines.append(
            f"{state} "
            f"#{key['key_number']} — "
            f"{mask_secret(key['api_key'])} — "
            f"{key['status']}"
        )

    await event.reply(
        f"🔑 API Key Pool — `{provider_name}`\n\n"
        + "\n".join(lines)
    )


@command(
    name="ارائه دهنده کلید فعال",
    permission="owner",
    chat_type="all",
    description="کلید فعال Pool یک Provider را مشخص می‌کند.",
)
async def activate_provider_api_key(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) != 2:
        await event.reply(
            "مثال:\n"
            "!ارائه دهنده کلید فعال gemini 2"
        )
        return

    provider_name = args[0]

    if not args[1].isdigit():
        await event.reply(
            "❌ شماره Key باید عدد باشد."
        )
        return

    key_number = int(args[1])

    provider = await self.providers.get(
        provider_name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{provider_name}» پیدا نشد."
        )
        return

    try:
        success = (
            await self.providers.activate_api_key(
                provider["id"],
                key_number,
            )
        )

    except Exception as exc:
        await event.reply(
            f"❌ تغییر Active Key ناموفق بود:\n{exc}"
        )
        return

    if not success:
        await event.reply(
            f"❌ Key #{key_number} برای Provider "
            f"«{provider_name}» پیدا نشد."
        )
        return

    await event.reply(
        f"✅ Key #{key_number} برای Provider "
        f"«{provider_name}» فعال شد."
    )


@command(
    name="ارائه دهنده کلید",
    permission="owner",
    chat_type="all",
    description="یک API Key از Pool Provider را تغییر می‌دهد.",
)
async def update_provider_api_key(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) != 3:
        await event.reply(
            "مثال:\n"
            "!ارائه دهنده کلید gemini 2 API_KEY"
        )
        return

    provider_name = args[0]

    if not args[1].isdigit():
        await event.reply(
            "❌ شماره Key باید عدد باشد."
        )
        return

    key_number = int(args[1])
    api_key = args[2]

    provider = await self.providers.get(
        provider_name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{provider_name}» پیدا نشد."
        )
        return

    try:
        success = (
            await self.providers.update_api_key(
                provider["id"],
                key_number,
                api_key,
            )
        )

    except Exception as exc:
        await event.reply(
            f"❌ بروزرسانی Key ناموفق بود:\n{exc}"
        )
        return

    if not success:
        await event.reply(
            f"❌ Key #{key_number} پیدا نشد."
        )
        return

    try:
        await event.delete()
    except Exception:
        pass

    await event.reply(
        f"✅ Key #{key_number} Provider "
        f"«{provider_name}» بروزرسانی شد."
    )


@command(
    name="ارائه دهنده کلید حذف",
    permission="owner",
    chat_type="all",
    description="یک API Key را از Pool Provider حذف می‌کند.",
)
async def delete_provider_api_key(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) != 2:
        await event.reply(
            "مثال:\n"
            "!ارائه دهنده کلید حذف gemini 2"
        )
        return

    provider_name = args[0]

    if not args[1].isdigit():
        await event.reply(
            "❌ شماره Key باید عدد باشد."
        )
        return

    key_number = int(args[1])

    provider = await self.providers.get(
        provider_name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{provider_name}» پیدا نشد."
        )
        return

    try:
        deleted = (
            await self.providers.delete_api_key(
                provider["id"],
                key_number,
            )
        )

    except Exception as exc:
        await event.reply(
            f"❌ حذف Key ناموفق بود:\n{exc}"
        )
        return

    if not deleted:
        await event.reply(
            f"❌ Key #{key_number} پیدا نشد."
        )
        return

    await event.reply(
        f"✅ Key #{key_number} از Pool Provider "
        f"«{provider_name}» حذف شد."
    )


@command(
    name="ارائه دهنده مدل ها",
    permission="owner",
    chat_type="all",
    description="مدل‌های موجود روی API یک Provider را می‌گیرد.",
)
async def provider_remote_models(
    self,
    event,
):
    provider_name = (
        event.args_text or ""
    ).strip()

    if not provider_name:
        await event.reply(
            "مثال: !ارائه دهنده مدل ها gemini"
        )
        return

    provider = await self.providers.get(
        provider_name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{provider_name}» پیدا نشد."
        )
        return

    keys = (
        await self.providers.get_available_api_keys(
            provider["id"]
        )
    )

    if not keys:
        await event.reply(
            f"❌ هیچ API Key قابل استفاده‌ای "
            f"در Pool Provider «{provider_name}» وجود ندارد."
        )
        return

    api_key_data = {
        "provider": provider["provider"],
        "api_key": keys[0]["api_key"],
        "base_url": provider["base_url"],
        "models_url": provider["models_url"],
    }

    try:
        models = (
            await self.gateway.list_remote_models(
                api_key_data
            )
        )

    except AIGatewayError as exc:
        await event.reply(
            f"❌ دریافت Modelها ناموفق بود:\n{exc}"
        )
        return

    if not models:
        await event.reply(
            f"📦 Provider «{provider_name}» هیچ مدلی برنگرداند."
        )
        return

    await event.reply(
        f"📦 Modelهای Provider «{provider_name}»:\n\n"
        + "\n".join(
            f"🔹 `{model}`"
            for model in models
        )
    )

@command(
    name="مدل آمار",
    permission="owner",
    chat_type="all",
    description="آمار و امتیازهای یک مدل را نشان می‌دهد.",
)
async def model_statistics(
    self,
    event,
):
    name = (
        event.args_text or ""
    ).strip()

    if not name:
        await event.reply(
            "❌ نام مدل را وارد کن.\n"
            "مثال:\n"
            "!مدل آمار <model_name>"
        )
        return

    model = await self.models.get(
        name
    )

    if model is None:
        await event.reply(
            f"❌ مدل «{name}» پیدا نشد."
        )
        return

    stats = (
        await self.store.model_statistics.get(
            model["name"]
        )
    )

    if stats is None:
        await event.reply(
            f"❌ برای مدل «{model['name']}» "
            "آماری ثبت نشده است."
        )
        return

    owner_score = stats['owner_score']
    reliability_score = stats['reliability_score']
    latency_score = stats['latency_score']
    overal_score = AIModelStatisticsStore.calculate_overall_score(stats)

    await event.reply(
        f"📊 آمار مدل «{model['name']}»\n\n"

        "⭐ امتیازها\n"
        f"{score_emoji(overal_score)} Overal Score: "
        f"{overal_score}/100\n"
        f"{score_emoji(owner_score)} Owner's consent: "
        f"{owner_score}/100\n"
        f"{score_emoji(reliability_score)} Reliability: "
        f"{reliability_score}/100\n"
        f"{score_emoji(latency_score)}Latency: "
        f"{latency_score}/100\n\n"

        "📈 آمار درخواست‌ها\n"
        f"• موفق: "
        f"{stats['success_count']:,}\n"
        f"• ناموفق: "
        f"{stats['failure_count']:,}\n\n"

        "❌ انواع خطا\n"
        f"• Rate Limit: "
        f"{stats['rate_limit_count']:,}\n"
        f"• Quota: "
        f"{stats['quota_count']:,}\n"
        f"• Timeout: "
        f"{stats['timeout_count']:,}\n"
        f"• Context: "
        f"{stats['context_error_count']:,}\n"
        f"• Authentication: "
        f"{stats['auth_error_count']:,}\n"
        f"• Server: "
        f"{stats['server_error_count']:,}\n"
        f"• Unknown: "
        f"{stats['unknown_error_count']:,}\n\n"

        "📡 Ping\n"
        f"• Success: "
        f"{stats['ping_success_count']:,}\n"
        f"• Failure: "
        f"{stats['ping_failure_count']:,}\n"
        f"• Total latency: "
        f"{stats['ping_total_latency_ms']:,.0f} ms\n"
        f"• Average latency: "
        f"{stats['ping_average_latency_ms']:,.0f} ms\n\n"

        "⏱️ latency\n"
        f"• Total: "
        f"{stats['total_latency_ms']:,.0f} ms\n"
        f"• Average: "
        f"{stats['average_latency_ms']:,.0f} ms\n\n"

        "🕒 آخرین وضعیت\n"
        f"• آخرین موفقیت: "
        f"{stats['last_success_at'] or 'ندارد'}\n"
        f"• آخرین شکست: "
        f"{stats['last_failure_at'] or 'ندارد'}\n"
        f"• آخرین خطا: "
        f"{stats['last_error'] or 'ندارد'}\n\n"

        f"• Last Ping success: "
        f"{stats['ping_last_success_at'] or 'None'}\n"
        f"• Last Ping failure: "
        f"{stats['ping_last_failure_at'] or 'None'}\n"
        f"• Last Ping error: "
        f"{stats['ping_last_error'] or 'None'}"
    )


@command(
    name="امتیاز مدل",
    permission="owner",
    chat_type="all",
    description="امتیاز رضایت Owner از یک مدل را تنظیم می‌کند.",
)
async def set_model_owner_score(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) != 2:
        await event.reply(
            "❌ استفاده نادرست.\n"
            "مثال:\n"
            "!امتیاز مدل gemini38flash 95"
        )
        return

    model_name = args[0]
    score_text = args[1]

    model = await self.models.get(
        model_name
    )

    if model is None:
        await event.reply(
            f"❌ مدل «{model_name}» پیدا نشد."
        )
        return

    if not score_text.isdigit():
        await event.reply(
            "❌ امتیاز باید یک عدد بین 0 تا 100 باشد."
        )
        return

    score = int(score_text)

    if not 0 <= score <= 100:
        await event.reply(
            "❌ امتیاز باید بین 0 تا 100 باشد."
        )
        return

    try:
        await self.store.model_statistics.set_scores(
            model["name"],
            owner_score=score,
        )

    except Exception as exc:
        print(
            f"❌ خطا در ثبت Owner Score مدل "
            f"{model['name']}: {exc}"
        )

        await event.reply(
            "❌ ذخیره امتیاز ناموفق بود."
        )
        return

    await event.reply(
        f"✅ Owner Score مدل "
        f"«{model['name']}» روی "
        f"{score}/100 تنظیم شد."
    )



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
    description="یک Model را به Provider متصل می‌کند.",
)
async def add_model(
    self,
    event,
):
    args = (
        event.args_text or ""
    ).strip().split()

    if len(args) != 3:
        await event.reply(
            "❌ استفاده نادرست.\n\n"
            "فرمت:\n"
            "!مدل افزودن <نام_مدل> <Provider> <Model_ID>\n\n"
            "مثال:\n"
            "!مدل افزودن gemini38flash "
            "gemini gemini-3.8-flash"
        )
        return

    model_name = args[0]
    provider_name = args[1]
    model_id = args[2]

    provider = await self.providers.get(
        provider_name
    )

    if provider is None:
        await event.reply(
            f"❌ Provider «{provider_name}» پیدا نشد."
        )
        return

    try:
        await self.models.add(
            name=model_name,
            provider=provider_name,
            model_id=model_id,
        )

    except Exception as exc:
        await event.reply(
            f"❌ خطا در افزودن Model:\n{exc}"
        )
        return

    try:
        await event.delete()
    except Exception:
        pass

    await event.reply(
        f"✅ Model «{model_name}» اضافه شد.\n\n"
        f"🔌 Provider: {provider_name}\n"
        f"🔧 LiteLLM: {provider['provider']}\n"
        f"🤖 Model ID: {model_id}\n"
        f"🔑 API Keyها از Pool همین Provider استفاده می‌کنند."
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
    name="مدل فعال گروه",
    permission="owner",
    chat_type="group",
    description="مدل ترجیحی این گروه را تنظیم می‌کند.",
)
async def activate_group_model(
    self,
    event,
):
    value = (
        event.args_text or ""
    ).strip()

    # ---------------------------------------------
    # نمایش وضعیت
    # ---------------------------------------------

    if not value:

        override = (
            await self.groups.get_model_override(
                event.chat_id
            )
        )

        if override:

            model = await self.models.get(
                override
            )

            if model is not None:
                await event.reply(
                    f"🎯 مدل این گروه: "
                    f"{model['name']}\n"
                    f"🔌 {model['provider']}/"
                    f"{model['model_id']}"
                )
                return

            await event.reply(
                f"⚠️ این گروه روی مدل «{override}» "
                f"تنظیم شده، ولی این مدل دیگر وجود ندارد.\n"
                f"🔄 در عمل از مدل سراسری استفاده می‌شود."
            )
            return

        global_model = (
            await self.models.get_active()
        )

        if global_model is None:
            await event.reply(
                "ℹ️ این گروه مدل اختصاصی ندارد "
                "و مدل سراسری هم تنظیم نشده است."
            )
            return

        await event.reply(
            "🌐 این گروه مدل اختصاصی ندارد.\n"
            f"🟢 مدل سراسری: {global_model['name']}"
        )
        return

    # ---------------------------------------------
    # Reset
    # ---------------------------------------------

    if value.lower() in {
        "ریست",
        "reset",
        "سراسری",
    }:

        cleared = (
            await self.groups.clear_model_override(
                event.chat_id
            )
        )

        if not cleared:
            await event.reply(
                "ℹ️ این گروه مدل اختصاصی نداشت."
            )
            return

        await event.reply(
            "✅ مدل اختصاصی گروه حذف شد؛ "
            "از این به بعد مدل سراسری استفاده می‌شود."
        )
        return

    # ---------------------------------------------
    # Validate Model
    # ---------------------------------------------

    model = await self.models.get(
        value
    )

    if model is None:
        await event.reply(
            f"❌ مدل «{value}» پیدا نشد."
        )
        return

    # ---------------------------------------------
    # Save Override
    # ---------------------------------------------

    await self.groups.set_model_override(
        event.chat_id,
        model["name"],
    )

    await event.reply(
        f"✅ مدل اختصاصی این گروه شد: "
        f"«{model['name']}»"
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
    description="جزئیات Model و Provider مربوط به آن",
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

    keys = await self.models.get_api_keys(
        model["name"]
    )

    key_lines = []

    for key in keys:

        state = (
            "🟢 Active"
            if key["is_active"]
            else "⚪"
        )

        key_lines.append(
            f"{state} "
            f"#{key['key_number']} — "
            f"{mask_secret(key['api_key'])} "
            f"[{key['status']}]"
        )

    provider = await self.providers.get(
        model["provider_id"]
    )

    provider_name = (
        provider["name"]
        if provider
        else model.get("provider_name", "?")
    )

    litellm_provider = (
        provider["provider"]
        if provider
        else model["provider"]
    )

    base_url = (
        provider["base_url"]
        if provider
        else model.get("base_url")
    )

    await event.reply(
        f"🤖 Model: `{model['name']}`\n"
        f"🔌 Provider: `{provider_name}`\n"
        f"🔧 LiteLLM Provider: `{litellm_provider}`\n"
        f"🆔 Model ID: `{model['model_id']}`\n"
        f"🌐 Base URL: "
        f"{base_url or 'پیش‌فرض'}\n\n"

        f"🔑 Shared API Key Pool ({len(keys)}):\n"
        + (
            "\n".join(key_lines)
            if key_lines
            else "هیچ API Key ثبت نشده."
        )
        + "\n\n"

        f"Active Model: "
        f"{'بله' if model['is_active'] else 'خیر'}"
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


@command(
    name="حداکثر کراکتر تایم لاین",
    permission="owner",
    chat_type="all",
    description="حداکثر تعداد کاراکتر Timeline را تنظیم می‌کند.",
)
async def maximum_timeline_chars(
    self,
    event,
) -> None:

    value = (
        event.args_text or ""
    ).strip()

    # نمایش مقدار فعلی
    if not value:
        current = (
            await self.store.timeline.get_max_chars()
        )

        await event.reply(
            "🧭 حداکثر کاراکتر Timeline:\n"
            f"{current:,} کاراکتر"
        )
        return

    if not value.isdigit():
        await event.reply(
            "❌ مقدار نامعتبر است.\n\n"
            "مثال:\n"
            "!حداکثر کراکتر تایم لاین 26000"
        )
        return

    max_chars = int(value)

    if max_chars < 1000:
        await event.reply(
            "❌ حداقل مقدار "
            "1000 کاراکتر است."
        )
        return

    await self.store.timeline.set_max_chars(
        max_chars
    )

    # همان لحظه روی RAM هم اعمال شود.
    self.timeline_max_chars = max_chars

    self.memory.set_timeline_max_chars(
        max_chars
    )

    await event.reply(
        "✅ حداکثر کاراکتر Timeline تنظیم شد.\n"
        f"📏 سقف: {max_chars:,} کاراکتر\n"
        "💾 در دیتابیس ذخیره شد."
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

        if event.sender_id is None:
            return

        # -------------------------------------------------
        # متن پیام
        # -------------------------------------------------

        text = (
            event.raw_text or ""
        ).strip()

        is_command = text.startswith("!")

        # -------------------------------------------------
        # Trigger detection
        # -------------------------------------------------
        try:
            trigger = (
                await self.groups.get_trigger(
                    event.chat_id,
                    self.default_trigger,
                )
            )
        except Exception as exc:
            print(
                f"⚠️ خطا در خوندن Trigger؛ "
                f"استفاده از پیش‌فرض: {exc}"
            )
            trigger = self.default_trigger

        trigger_text = None
        reply_to_booby = False

        # Commandها نباید بوبی را Trigger کنند.
        # پیام خالی/رسانه‌ای هم AI را Trigger نمی‌کند،
        # ولی همچنان باید وارد Timeline شود.
        if text and not is_command:

            trigger_text = extract_trigger_text(
                text,
                trigger,
            )

            # -------------------------------------------------
            # Reply به پیام بوبی = Trigger
            # -------------------------------------------------

            if getattr(
                event,
                "is_reply",
                False,
            ):
                try:
                    replied = (
                        await event.get_reply_message()
                    )

                except Exception:
                    replied = None

                replied_sender_id = (
                    getattr(
                        replied,
                        "sender_id",
                        None,
                    )
                    if replied is not None
                    else None
                )

                if (
                    replied_sender_id is not None
                    and self.bot_user_id is not None
                ):
                    try:
                        reply_to_booby = (
                            int(replied_sender_id)
                            == int(self.bot_user_id)
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):
                        reply_to_booby = False

                if reply_to_booby:
                    # وقتی Reply به بوبی است،
                    # خود متن کامل کاربر Prompt است.
                    trigger_text = text

        # -------------------------------------------------
        # Timeline
        # -------------------------------------------------
        # Timeline مستقل از Trigger است.
        # هر پیام گروه باید اینجا ثبت شود.
        #
        # record_event خودش Commandها را حذف می‌کند،
        # بنابراین لازم نیست اینجا فیلترشان کنیم.

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
        # اگر پیام بوبی را Trigger نکرده، فقط Timeline
        # ثبت شده و نباید وارد پردازش AI شویم.
        # -------------------------------------------------

        if (
            not text
            or is_command
        ):
            return

        if (
            trigger_text is None
            and not reply_to_booby
        ):
            return

        telemetry_enabled = (
            self.telemetry.enabled
        )

        telemetry_total_started = (
            time.perf_counter()
            if telemetry_enabled
            else None
        )

        telemetry_emitted = False

        group_model_override = None

        try:
            group_model_override = (
                await self.groups.get_model_override(
                    event.chat_id
                )
            )

        except Exception as exc:
            print(
                f"⚠️ خطا در خواندن Group Model Override؛ "
                f"استفاده از مدل سراسری: {exc}"
            )

        active_model = None

        try:
            active_model = (
                await self.models.get_active()
            )
        except Exception:
            active_model = None

        telemetry_model_name = None

        telemetry_model = active_model

        if group_model_override:
            try:
                override_model = (
                    await self.models.get(
                        group_model_override
                    )
                )

                if override_model is not None:
                    telemetry_model = override_model

            except Exception:
                pass

        if telemetry_model is not None:
            try:
                telemetry_model_name = (
                    self.gateway._litellm_model(
                        telemetry_model
                    )
                )
            except Exception:
                telemetry_model_name = (
                    telemetry_model.get(
                        "model_id"
                    )
                )




        


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
        try:
            await self.memory.store.add_message(
                event.chat_id,
                "user",
                user_content,
                event.sender_id,
            )
        except Exception as exc:
            print(
                f"⚠️ ذخیره‌ی پیام کاربر در حافظه ناموفق بود: {exc}"
            )

        await self.memory.maybe_trim(
            event.chat_id
        )

        # -------------------------------------------------
        # Build Context
        # -------------------------------------------------

        try:
            system_prompt = (
                await self.groups.get_system_prompt(
                    event.chat_id
                )
            )
        except Exception as exc:
            print(
                f"⚠️ خطا در خوندن System Prompt؛ "
                f"استفاده از پیش‌فرض: {exc}"
            )
            system_prompt = (
                self.groups.DEFAULT_SYSTEM_PROMPT
            )

        context = (
            await self.memory.build_context(
                event.chat_id,
                system_prompt,
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
        request_timeout = min(
            180.0,
            max(60.0, context_chars / 150),
        )


        if telemetry_enabled:
            telemetry_request_started = (
                time.perf_counter()
            )

            answer, model_info = (
                await self.gateway.chat(
                    context,
                    preferred_model_name=(
                        group_model_override
                    ),
                    return_metadata=True,
                    timeout=request_timeout
                )
            )

        else:
            answer = await self.gateway.chat(
                context,
                preferred_model_name=(
                    group_model_override
                ),
                timeout=request_timeout
            )

            model_info = {}



        # -------------------------------------------------
        # AI TELEMETRY
        #
        # این فقط یک put_nowait داخل Queue است.
        # هیچ Network / DB / Tokenization ندارد.
        # -------------------------------------------------

        if telemetry_enabled:

            request_latency_ms = (
                (
                    time.perf_counter()
                    - telemetry_request_started
                )
                * 1000
            )

            total_duration_ms = (
                (
                    time.perf_counter()
                    - telemetry_total_started
                )
                * 1000
            )

            self.telemetry.emit_success(
                event=event,
                sender=sender,
                group_id=event.chat_id,
                trigger=trigger,
                context=context,
                answer=answer,
                latency_ms=request_latency_ms,
                total_duration_ms=(
                    total_duration_ms
                ),
                model_info=model_info,
                model_name=telemetry_model_name,
            )

            telemetry_emitted = True




        # -------------------------------------------------
        # DEBUG: پاسخ دریافت شد
        # -------------------------------------------------

        print(
            f"✅ BOOBY AI RESPONSE | "
            f"group={event.chat_id} | "
            f"chars={len(answer)}"
        )
        try:
            await self.memory.store.add_message(
                event.chat_id,
                "assistant",
                answer,
            )
        except Exception as exc:
            print(
                f"⚠️ ذخیره‌ی پیام ربات در حافظه ناموفق بود: {exc}"
            )

        # -------------------------------------------------
        # ارسال پاسخ
        # -------------------------------------------------

        sent = None

        try:
            sent = await event.reply(
                answer[:4000]
            )
        except Exception:
            try:
                sent = await event.respond(
                    answer[:4000]
                )
            except Exception as exc:
                print(
                    f"⚠️ ارسال پاسخ بوبی ناموفق بود: {exc}"
                )

        try:
            await self.memory.store.add_message(
                event.chat_id,
                "assistant",
                answer,
            )
        except Exception as exc:
            print(
                f"⚠️ ذخیره‌ی پاسخ بوبی در حافظه ناموفق بود: {exc}"
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

        if (
            telemetry_enabled
            and not telemetry_emitted
        ):

            request_latency_ms = None

            if telemetry_request_started is not None:
                request_latency_ms = (
                    (
                        time.perf_counter()
                        - telemetry_request_started
                    )
                    * 1000
                )

            total_duration_ms = None

            if telemetry_total_started is not None:
                total_duration_ms = (
                    (
                        time.perf_counter()
                        - telemetry_total_started
                    )
                    * 1000
                )

            self.telemetry.emit_failure(
                event=event,
                sender=sender,
                group_id=event.chat_id,
                trigger=trigger,
                context=context,
                error=exc,
                request_latency_ms=(
                    request_latency_ms
                ),
                total_duration_ms=(
                    total_duration_ms
                ),
                stage="AI Gateway",
                model_name=telemetry_model_name,
            )

            telemetry_emitted = True

        try:
            await event.reply(
                "❌ بوبی فعلاً نتونست پاسخ بده. "
                "لطفاً دوباره امتحان کن."
            )

        except Exception:
            pass



    except Exception as exc:

        print(
            "❌ خطای غیرمنتظره در "
            "AI Message Handler:"
        )

        traceback.print_exc()

        if (
            "telemetry_enabled" in locals()
            and telemetry_enabled
            and not telemetry_emitted
        ):

            request_latency_ms = None

            if telemetry_request_started is not None:
                request_latency_ms = (
                    (
                        time.perf_counter()
                        - telemetry_request_started
                    )
                    * 1000
                )

            total_duration_ms = None

            if telemetry_total_started is not None:
                total_duration_ms = (
                    (
                        time.perf_counter()
                        - telemetry_total_started
                    )
                    * 1000
                )

            self.telemetry.emit_failure(
                event=event,
                model_name=telemetry_model_name,
                sender=sender
                if "sender" in locals()
                else None,
                group_id=event.chat_id,
                trigger=trigger
                if "trigger" in locals()
                else "بوبی",
                context=context
                if "context" in locals()
                else None,
                error=exc,
                request_latency_ms=(
                    request_latency_ms
                ),
                total_duration_ms=(
                    total_duration_ms
                ),
                stage="AI Message Handler",
            )

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

@on_bus_event(
    "timeline_deletion"
)
async def on_timeline_deletion(
    self,
    event,
    group_id: int,
    message_id: int | None = None,
    source: str = "unknown",
    reason: str | None = None,
    matched_word: str | None = None,
) -> None:

    if not self.timeline_enabled:
        return

    if message_id is None:
        message_id = (
            self.memory._extract_message_id(
                event
            )
        )

    if message_id is None:
        return

    self.memory.mark_deleted(
        group_id=group_id,
        event=event,
        message_id=message_id,
        source=source,
        reason=reason,
        matched_word=matched_word,
    )
@on_bus_event("violation")
async def on_violation_deleted(
    self,
    event,
    group_id: int,
    user_id: int,
    reason: str,
    message_ids: list[int] | None = None,
    spam_type: str | None = None,
    violation_score: int = 1,
    confidence: int = 0,
    source: str = "unknown",
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