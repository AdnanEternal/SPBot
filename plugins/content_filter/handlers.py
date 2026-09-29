from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_event
from core.permissions import is_chat_admin, is_owner

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
        target_group
        remaining_args
        remote
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
    local_admin: bool = False,
) -> tuple[int | None, str, bool]:
    """
    مقصد گروه را مشخص می‌کند.

    اجرای محلی:
        فقط داخل گروه و در صورت نیاز با دسترسی Admin.

    اجرای ریموت:
        فقط Owner مجاز است.
    """

    (
        target_group,
        remaining,
        remote,
    ) = _extract_optional_group_target(
        event.args_text or ""
    )

    # =================================================
    # REMOTE
    # =================================================

    if remote:

        if not is_owner(
            event.sender_id
        ):
            await event.reply(
                "❌ اجرای ریموت این کامند فقط "
                "برای Owner مجازه."
            )

            return (
                None,
                remaining,
                True,
            )

        return (
            target_group,
            remaining,
            True,
        )

    # =================================================
    # LOCAL
    # =================================================

    if not event.is_group:
        return (
            None,
            remaining,
            False,
        )

    target_group = event.chat_id

    if local_admin:

        try:
            allowed = await is_chat_admin(
                self.client,
                await event.get_chat(),
                event.sender_id,
                raise_on_error=True,
            )

        except Exception as e:
            print(
                "⚠️ بررسی دسترسی ادمین "
                f"برای Content Filter ناموفق بود: {e}"
            )

            await event.reply(
                "❌ نتونستم دسترسی ادمین شما "
                "رو بررسی کنم."
            )

            return (
                None,
                remaining,
                False,
            )

        if not allowed:
            await event.reply(
                "❌ این کامند فقط برای ادمین‌های گروه مجازه."
            )

            return (
                None,
                remaining,
                False,
            )

    return (
        target_group,
        remaining,
        False,
    )


# =====================================================
# ADD FILTER
# =====================================================


@command(
    name="فیلتر",
    permission="everyone",
    chat_type="all",
    description="یک کلمه رو به لیست فیلتر این گروه اضافه می‌کنه.",
)
async def add_word(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    (
        target_group,
        word,
        _,
    ) = await _resolve_group_target(
        self,
        event,
        local_admin=True,
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "داخل گروه:\n"
            "!فیلتر کلمه\n\n"
            "ریموت توسط Owner:\n"
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


# =====================================================
# REMOVE FILTER
# =====================================================


@command(
    name="حذف فیلتر",
    permission="everyone",
    chat_type="all",
    description="یک کلمه رو از لیست فیلتر این گروه حذف می‌کنه.",
)
async def remove_word(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    (
        target_group,
        word,
        _,
    ) = await _resolve_group_target(
        self,
        event,
        local_admin=True,
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "داخل گروه:\n"
            "!حذف فیلتر کلمه\n\n"
            "ریموت توسط Owner:\n"
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


# =====================================================
# LIST FILTER
# =====================================================


@command(
    name="لیست فیلتر",
    permission="everyone",
    chat_type="all",
    description="لیست کلمات فیلترشده‌ی این گروه رو نشون می‌ده.",
)
async def list_words(
    self: "ContentFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    (
        target_group,
        remaining,
        _,
    ) = await _resolve_group_target(
        self,
        event,
        local_admin=True,
    )

    if target_group is None:
        await event.reply(
            "❌ در PV باید شناسه گروه را وارد کنی.\n"
            "ریموت توسط Owner:\n"
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


# =====================================================
# ADMIN FILTER PERMISSION
# =====================================================


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
    (
        target_group,
        remaining,
        _,
    ) = await _resolve_group_target(
        self,
        event,
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

    # ---------------------------------------------
    # STATUS
    # ---------------------------------------------

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

    # ---------------------------------------------
    # SET
    # ---------------------------------------------

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


# =====================================================
# CONTENT FILTER
# =====================================================


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

    # ادمین‌ها در حالت مجاز اصلاً فیلتر نمی‌شوند.
    if admins_allowed and is_admin:
        return

    # ---------------------------------------------
    # اطلاع‌رسانی
    # ---------------------------------------------

    try:
        sender_name = (
            "@" + event.sender.username
            if event.sender.username
            else event.sender.first_name
        )

        await event.reply(
            f"{sender_name} ⚠️ پیام شما به‌دلیل استفاده از "
            "کلمهٔ فیلترشده حذف شد."
        )

    except Exception as e:
        print(
            "⚠️ نتونستم اعلان فیلتر شدن پیام "
            f"رو ارسال کنم: {e}"
        )

    # ---------------------------------------------
    # حذف پیام
    # ---------------------------------------------

    try:
        await self.event_bus.emit(
            "timeline_deletion",
            event=event,
            group_id=event.chat_id,
            message_id=getattr(
                event,
                "id",
                None,
            ),
            source="content_filter",
            reason="filtered_content",
            matched_word=matched_word,
        )
        await event.delete()

    except Exception as e:
        print(
            "⚠️ نتونستم پیام فیلترشده "
            f"رو پاک کنم: {e}"
        )

    # ---------------------------------------------
    # ADMIN
    # ---------------------------------------------

    # اگر ادمین مشمول فیلتر بوده،
    # فقط پیام حذف می‌شود و هیچ سابقه‌ای ثبت نمی‌شود.
    if is_admin:
        return

    # ---------------------------------------------
    # RECORD
    # ---------------------------------------------

    await self.violations.add(
        group_id=event.chat_id,
        user_id=event.sender_id,
        word=matched_word,
    )

    count = await self.violations.get_count(
        event.chat_id,
        event.sender_id,
    )

    # سقف پیش‌فرض = 3
    #
    # تخلف 1 -> ثبت
    # تخلف 2 -> ثبت
    # تخلف 3 -> ثبت
    # تخلف 4 -> ثبت + درخواست مجازات
    if count <= self.MAX_VIOLATIONS:
        return

    # Content Filter خودش مجازات نمی‌کند.
    # فقط از سیستم مجازات درخواست اجرای مجازات می‌کند.
    await self.event_bus.emit(
        "punishment_request",
        event=event,
        group_id=event.chat_id,
        user_id=event.sender_id,
        reason="استفاده مکرر از کلمات فیلترشده",
        source="content_filter",
    )