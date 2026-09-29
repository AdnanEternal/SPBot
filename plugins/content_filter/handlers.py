from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_event, on_bus_event
from core.permissions import is_chat_admin

if TYPE_CHECKING:
    from .plugin import ContentFilterPlugin


def _is_remote_group_id(
    value: str,
) -> bool:
    """
    شناسه‌ی گروه ریموت را تشخیص می‌دهد.
    فقط tokenهای عددی منفی به‌عنوان مقصد ریموت پذیرفته می‌شوند.
    """

    if not value:
        return False

    try:
        return int(value) < 0
    except (TypeError, ValueError):
        return False


def _extract_optional_group_target(
    raw: str,
) -> tuple[int | None, str, bool]:
    """
    اگر آخرین آرگومان یک شناسه‌ی گروه منفی باشد،
    آن را از آرگومان‌ها جدا می‌کند.

    خروجی:
        (target_group, remaining_args, remote)
    """

    raw = (
        raw or ""
    ).strip()

    if not raw:
        return (
            None,
            "",
            False,
        )

    parts = raw.split()

    candidate = parts[-1]

    if not _is_remote_group_id(
        candidate
    ):
        return (
            None,
            raw,
            False,
        )

    try:
        target_group = int(
            candidate
        )

    except (
        TypeError,
        ValueError,
    ):
        return (
            None,
            raw,
            False,
        )

    return (
        target_group,
        " ".join(
            parts[:-1]
        ).strip(),
        True,
    )


async def _resolve_group_target(
    self: "ContentFilterPlugin",
    event,
    *,
    require_admin: bool = False,
) -> tuple[int | None, str, bool]:
    """
    مقصد گروه را مشخص می‌کند.

    داخل گروه:
        !فیلتر کلمه
        -> گروه فعلی

    ریموت:
        !فیلتر کلمه -100123456
        -> گروه ریموت

    در عملیات admin ریموت، ادمین بودن کاربر
    در خود گروه مقصد هم بررسی می‌شود.
    """

    (
        target_group,
        remaining,
        remote,
    ) = _extract_optional_group_target(
        event.args_text or ""
    )

    if target_group is None:

        if event.is_group:
            target_group = event.chat_id

        else:
            return (
                None,
                remaining,
                False,
            )

    if require_admin and remote:

        try:
            if target_group == event.chat_id:
                target_chat = (
                    await event.get_chat()
                )

            else:
                target_chat = (
                    await self.client.get_entity(
                        target_group
                    )
                )

            allowed = await is_chat_admin(
                self.client,
                target_chat,
                event.sender_id,
                raise_on_error=True,
            )

        except Exception as e:
            print(
                "⚠️ بررسی دسترسی ادمین گروه مقصد "
                f"ناموفق بود: {e}"
            )

            await event.reply(
                "❌ نتونستم دسترسی ادمین شما "
                "در گروه مقصد رو بررسی کنم."
            )

            return (
                None,
                remaining,
                remote,
            )

        if not allowed:
            await event.reply(
                "❌ شما در گروه مقصد ادمین نیستید."
            )

            return (
                None,
                remaining,
                remote,
            )

    return (
        target_group,
        remaining,
        remote,
    )





@command(
    name="فیلتر",
    permission="admin",
    chat_type="all",
    description="یک کلمه رو به لیست فیلتر این گروه اضافه می‌کنه.",
)
async def add_word(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, word, _ = await _resolve_group_target(
        self,
        event,
        require_admin=True,
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "داخل گروه:\n"
            "!فیلتر کلمه\n\n"
            "برای گروه دیگر:\n"
            "!فیلتر کلمه -100123456"
        )
        return

    if not word:
        await event.reply(
            "مثال:\n"
            "!فیلتر کلمه\n"
            "!فیلتر کلمه -100123456"
        )
        return

    await self.words.add(
        target_group,
        word,
    )

    await event.reply(
        f"✅ کلمه «{word}» به لیست فیلتر گروه "
        f"`{target_group}` اضافه شد."
    )


@command(
    name="حذف فیلتر",
    permission="admin",
    chat_type="all",
    description="یک کلمه رو از لیست فیلتر این گروه حذف می‌کنه.",
)
async def remove_word(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
 
    target_group, word, _ = await _resolve_group_target(
        self,
        event,
        require_admin=True,
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "داخل گروه:\n"
            "!حذف فیلتر کلمه\n\n"
            "برای گروه دیگر:\n"
            "!حذف فیلتر کلمه -100123456"
        )
        return

    if not word:
        await event.reply(
            "مثال:\n"
            "!حذف فیلتر کلمه\n"
            "!حذف فیلتر کلمه -100123456"
        )
        return

    removed = await self.words.remove(
        target_group,
        word,
    )

    if removed:
        await event.reply(
            f"✅ کلمه «{word}» از لیست فیلتر گروه "
            f"`{target_group}` حذف شد."
        )
    else:
        await event.reply(
            f"ℹ️ کلمه «{word}» در لیست فیلتر گروه "
            f"`{target_group}` وجود نداشت."
        )

@command(
    name="لیست فیلتر",
    permission="admin",
    chat_type="all",
    description="لیست کلمات فیلترشده‌ی این گروه رو نشون می‌ده.",
)
async def list_words(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:

    target_group, remaining, _ = (
        await _resolve_group_target(
            self,
            event,
            require_admin=True,
        )
    )

    if target_group is None:
        await event.reply(
            "❌ در PV باید شناسه گروه را وارد کنی.\n"
            "مثال:\n"
            "!لیست فیلتر -100123456"
        )
        return

    if remaining:
        await event.reply(
            "❌ استفاده نادرست.\n"
            "مثال:\n"
            "!لیست فیلتر\n"
            "!لیست فیلتر -100123456"
        )
        return

    words = await self.words.get_all(
        target_group
    )

    if not words:
        await event.reply(
            f"📋 لیست فیلتر گروه `{target_group}` خالیه."
        )
        return

    await event.reply(
        f"📋 کلمات فیلترشده گروه "
        f"`{target_group}`:\n\n"
        + "\n".join(
            sorted(words)
        )
    )

@command(
    name="فیلتر ادمین",
    permission="owner",
    chat_type="all",
    description=(
        "تعیین می‌کنه ادمین‌های گروه اجازه استفاده "
        "از کلمات فیلترشده رو داشته باشن یا نه."
    ),
)
async def set_admin_filter_permission(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:

    target_group, remaining, _ = (
        await _resolve_group_target(
            self,
            event,
        )
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!فیلتر ادمین مجاز -100123456"
        )
        return

    value = (
        remaining or ""
    ).strip().casefold()

    if not value:
        allowed = (
            await self.settings.get_admins_allowed(
                target_group
            )
        )

        status = (
            "مجاز"
            if allowed
            else "ممنوع"
        )

        await event.reply(
            f"⚙️ استفاده ادمین‌های گروه "
            f"`{target_group}` از کلمات فیلترشده: "
            f"{status}\n\n"
            "تغییر:\n"
            f"`!فیلتر ادمین مجاز {target_group}`\n"
            f"`!فیلتر ادمین ممنوع {target_group}`"
        )
        return

    if value == "مجاز":
        allowed = True

    elif value == "ممنوع":
        allowed = False

    else:
        await event.reply(
            "❌ استفاده نادرست.\n\n"
            "مثال:\n"
            f"`!فیلتر ادمین مجاز {target_group}`\n"
            f"`!فیلتر ادمین ممنوع {target_group}`"
        )
        return

    await self.settings.set_admins_allowed(
        target_group,
        allowed,
    )

    status = (
        "می‌تونن"
        if allowed
        else "نمی‌تونن"
    )

    await event.reply(
        f"✅ ادمین‌های گروه `{target_group}` "
        f"از این به بعد {status} از کلمات "
        "فیلترشده استفاده کنن."
    )

@on_event(events.NewMessage(incoming=True))
async def on_message(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    if not event.is_group:
        return

    text = (
        event.raw_text or ""
    )

    matched_word = await self.words.find_match(
        event.chat_id,
        text,
    )

    if matched_word is None:
        return

    admins_allowed = (
        await self.settings.get_admins_allowed(
            event.chat_id
        )
    )

    # ادمین بودن را همیشه بررسی می‌کنیم.
    # حتی وقتی admins_allowed=False باشد.
    is_admin = False

    try:
        is_admin = await is_chat_admin(
            self.client,
            await event.get_chat(),
            event.sender_id,
            raise_on_error=True,
        )

    except Exception as e:
        print(
            "⚠️ بررسی ادمین برای "
            f"Content Filter ناموفق بود: {e}"
        )

    # اگر ادمین‌ها مجاز باشند،
    # پیام ادمین اصلاً فیلتر نمی‌شود.
    if admins_allowed and is_admin:
        return

    # اول اعلان را به‌صورت Reply می‌فرستیم
    # تا کاربر بفهمد دقیقاً کدام پیام حذف شده.
    try:
        await event.reply(
            "⚠️ این پیام به‌دلیل استفاده از "
            "کلمهٔ فیلترشده حذف شد."
        )

    except Exception as e:
        print(
            "⚠️ نتونستم اعلان فیلتر شدن پیام "
            f"رو ارسال کنم: {e}"
        )

    # بعد خود پیام حذف می‌شود.
    try:
        await event.delete()

    except Exception as e:
        print(
            "⚠️ نتونستم پیام فیلترشده "
            f"رو پاک کنم: {e}"
        )

    # ادمین مشمول فیلتر بوده،
    # اما نباید سابقه‌ی violation داشته باشد.
    if is_admin:
        return

    # فقط کاربران عادی وارد سیستم تخلفات می‌شوند.
    await self.event_bus.emit(
        event_name="violation",
        event=event,
        group_id=event.chat_id,
        user_id=event.sender_id,
        reason=(
            f"استفاده از کلمه «{matched_word}» ممنوع است."
        ),
    )

@on_bus_event("spam_signals")
async def contribute_spam_signals(
    self: "ContentFilterPlugin",
    event,
    group_id: int,
    user_id: int,
    signals: dict,
) -> None:
    if not event.is_group:
        return

    # ادمین بودن همیشه بررسی می‌شود.
    # ادمین‌ها نباید از این پلاگین سیگنال تخلف بگیرند.
    is_admin = False

    try:
        is_admin = await is_chat_admin(
            self.client,
            await event.get_chat(),
            user_id,
            raise_on_error=True,
        )

    except Exception as e:
        print(
            "⚠️ بررسی ادمین برای Spam Signal "
            f"ناموفق بود: {e}"
        )

    if is_admin:
        return

    matched_word = getattr(
        event,
        "_content_filter_match",
        None,
    )

    if matched_word is None:
        matched_word = await self.words.find_match(
            group_id,
            event.raw_text or "",
        )

        if matched_word is not None:
            event._content_filter_match = (
                matched_word
            )

    if matched_word is None:
        return

    signals[
        "content_filter_match"
    ] = True

    signals[
        "content_filter_word"
    ] = matched_word