from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import command, on_event, on_bus_event
from core.permissions import is_chat_admin

from . import detection
from .actions import apply_decision
from .engine import build_features, decide, calculate_score

if TYPE_CHECKING:
    from .plugin import SpamFilterPlugin


def _is_remote_group_id(
    value: str,
) -> bool:
    if not value:
        return False

    try:
        return int(value) < 0
    except ValueError:
        return False


def _extract_optional_group_target(
    raw: str,
) -> tuple[int | None, str]:
    parts = raw.strip().split()

    if not parts:
        return None, ""

    candidate = parts[-1]

    if not _is_remote_group_id(candidate):
        return None, raw.strip()

    return (
        int(candidate),
        " ".join(parts[:-1]).strip(),
    )


def _resolve_spam_group_target(
    event,
) -> tuple[int | None, str]:
    raw = (
        event.args_text or ""
    ).strip()

    target_group, clean_args = (
        _extract_optional_group_target(
            raw
        )
    )

    if target_group is not None:
        return target_group, clean_args

    if event.is_group:
        return event.chat_id, clean_args

    return None, clean_args


@command(
    name="اسپم معاف",
    permission="admin",
    chat_type="all",
    description="یک کاربر را از Spam Filter معاف می‌کند.",
)
async def add_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!اسپم معاف 49245702 -10024473944"
        )
        return

    if not args.isdigit():
        await event.reply(
            "❌ شناسه کاربر باید عددی باشد.\n"
            "مثال:\n"
            "!اسپم معاف 49245702"
        )
        return

    user_id = int(args)

    added = await self.whitelist.add(
        target_group,
        user_id,
    )

    if not added:
        await event.reply(
            f"ℹ️ کاربر `{user_id}` از قبل "
            f"از Spam Filter معاف است."
        )
        return

    await event.reply(
        f"✅ کاربر `{user_id}` از Spam Filter "
        f"گروه `{target_group}` معاف شد."
    )


@command(
    name="اسپم رفع معافیت",
    permission="admin",
    chat_type="all",
    description="معافیت یک کاربر از Spam Filter را لغو می‌کند.",
)
async def remove_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!اسپم رفع معافیت 49245702 -10024473944"
        )
        return

    if not args.isdigit():
        await event.reply(
            "❌ شناسه کاربر باید عددی باشد.\n"
            "مثال:\n"
            "!اسپم رفع معافیت 49245702"
        )
        return

    user_id = int(args)

    removed = await self.whitelist.remove(
        target_group,
        user_id,
    )

    if not removed:
        await event.reply(
            f"ℹ️ کاربر `{user_id}` در لیست معافیت "
            f"وجود ندارد."
        )
        return

    await event.reply(
        f"✅ معافیت کاربر `{user_id}` از Spam Filter "
        f"لغو شد."
    )


@command(
    name="اسپم معاف ها",
    permission="admin",
    chat_type="all",
    description="لیست کاربران معاف از Spam Filter را نشان می‌دهد.",
)
async def list_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!اسپم معاف ها -10024473944"
        )
        return

    if args:
        await event.reply(
            "❌ استفاده نادرست.\n"
            "مثال:\n"
            "!اسپم معاف ها\n"
            "یا:\n"
            "!اسپم معاف ها -10024473944"
        )
        return

    users = await self.whitelist.get_all(
        target_group
    )

    if not users:
        await event.reply(
            f"📋 لیست معافیت Spam Filter گروه "
            f"`{target_group}` خالی است."
        )
        return

    lines = [
        f"• `{user_id}`"
        for user_id in users
    ]

    await event.reply(
        f"📋 کاربران معاف از Spam Filter\n"
        f"گروه: `{target_group}`\n\n"
        + "\n".join(lines)
    )


@command(
    name="اسپم فلاد",
    permission="admin",
    chat_type="group",
    description="حداکثر تعداد پیام مجاز در یه بازه‌ی زمانی رو تنظیم می‌کنه.",
)
async def set_flood(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    parts = event.args_text.split()

    if (
        len(parts) != 2
        or not all(p.isdigit() for p in parts)
    ):
        await event.reply(
            "مثال: !اسپم فلاد 5 10\n"
            "(یعنی بیشتر از ۵ پیام تو ۱۰ ثانیه = اسپم)"
        )
        return

    count, seconds = (
        int(parts[0]),
        int(parts[1]),
    )

    await self.settings.set_flood(
        event.chat_id,
        count,
        seconds,
    )

    await event.reply(
        f"آستانه‌ی فلاد با موفقیت روی "
        f"«بیشتر از {count} پیام در {seconds} ثانیه» تنظیم شد!"
    )


@command(
    name="اسپم لینک",
    permission="admin",
    chat_type="group",
    description="حداکثر تعداد لینک مجاز تو یه پیام رو تنظیم می‌کنه.",
)
async def set_max_links(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    value = event.args_text.strip()

    if not value.isdigit():
        await event.reply(
            "مثال: !اسپم لینک 3"
        )
        return

    await self.settings.set_max_links(
        event.chat_id,
        int(value),
    )

    await event.reply(
        f"حداکثر لینک مجاز تو هر پیام "
        f"با موفقیت به {value} تنظیم شد!"
    )


@command(
    name="اسپم تکرار",
    permission="admin",
    chat_type="group",
    description="حداکثر پیام تکراریِ پشت‌سرهم مجاز رو تنظیم می‌کنه.",
)
async def set_max_repeat(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    value = event.args_text.strip()

    if not value.isdigit():
        await event.reply(
            "مثال: !اسپم تکرار 3"
        )
        return

    await self.settings.set_max_repeat(
        event.chat_id,
        int(value),
    )

    await event.reply(
        f"حداکثر پیام تکراری مجاز "
        f"با موفقیت به {value} تنظیم شد!"
    )


@command(
    name="تنظیمات اسپم",
    permission="admin",
    chat_type="group",
    description="تنظیمات فعلی فیلتر اسپم این گروه رو نشون می‌ده.",
)
async def show_settings(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    settings = await self.settings.get(
        event.chat_id
    )

    await event.reply(
        "⚙️ تنظیمات فیلتر اسپم این گروه:\n\n"
        f"فلاد: بیشتر از "
        f"{settings['flood_count']} پیام در "
        f"{settings['flood_seconds']} ثانیه\n"
        f"لینک: بیشتر از "
        f"{settings['max_links']} لینک تو یه پیام\n"
        f"تکرار: بیشتر از "
        f"{settings['max_repeat']} پیام یکسان پشت‌سرهم"
    )


@command(
    name="اسپم قانون بیو",
    permission="owner",
    chat_type="all",
    description="یک قانون Bio به Spam Filter اضافه می‌کند.",
)
async def add_bio_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده.\n"
            "مثال:\n"
            "!اسپم قانون بیو تبلیغ -10024473944"
        )
        return

    pattern = args.strip()

    if not pattern:
        await event.reply(
            "❌ متن قانون مشخص نشده."
        )
        return

    added = await self.rules.add_bio_rule(
        target_group,
        pattern,
    )

    if not added:
        await event.reply(
            "ℹ️ این قانون از قبل وجود دارد."
        )
        return

    await event.reply(
        f"✅ قانون Bio اضافه شد.\n"
        f"گروه: `{target_group}`\n"
        f"عبارت: `{pattern}`\n"
        f"اقدام: `HARD_SPAM`"
    )


@command(
    name="اسپم حذف قانون بیو",
    permission="owner",
    chat_type="all",
    description="یک قانون Bio را حذف می‌کند.",
)
async def remove_bio_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    pattern = args.strip()

    if not pattern:
        await event.reply(
            "❌ متن قانون مشخص نشده."
        )
        return

    removed = await self.rules.remove_bio_rule(
        target_group,
        pattern,
    )

    if not removed:
        await event.reply(
            "❌ این قانون پیدا نشد."
        )
        return

    await event.reply(
        f"✅ قانون Bio حذف شد.\n"
        f"عبارت: `{pattern}`"
    )


@command(
    name="اسپم قوانین بیو",
    permission="owner",
    chat_type="all",
    description="قوانین Bio ثبت‌شده را نشان می‌دهد.",
)
async def list_bio_rules(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = _resolve_spam_group_target(
        event
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    if args:
        await event.reply(
            "❌ استفاده نادرست."
        )
        return

    rules = await self.rules.get_all(
        target_group
    )

    rules = [
        rule
        for rule in rules
        if rule["rule_type"] == "bio_contains"
    ]

    if not rules:
        await event.reply(
            f"📋 برای گروه `{target_group}` "
            f"هیچ قانون Bio ثبت نشده."
        )
        return

    lines = [
        f"{index}. `{rule['pattern']}` → `HARD_SPAM`"
        for index, rule in enumerate(
            rules,
            start=1,
        )
    ]

    await event.reply(
        f"📋 قوانین Bio\n"
        f"گروه: `{target_group}`\n\n"
        + "\n".join(lines)
    )


@on_event(events.NewMessage(incoming=True))
async def on_message(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    if (
        not event.is_group
        or event.sender_id is None
    ):
        return

    if await self.whitelist.is_exempt(
        event.chat_id,
        event.sender_id,
    ):
        return

    text = event.raw_text or ""

    settings = await self.settings.get(
        event.chat_id
    )

    repeat_count = self.tracker.register(
        event.chat_id,
        event.sender_id,
        event.id,
        text,
    )

    recent_message_count = (
        self.tracker.count_in_window(
            event.chat_id,
            event.sender_id,
            settings["flood_seconds"],
        )
    )

    recent_texts = (
        self.tracker.recent_texts(
            event.chat_id,
            event.sender_id,
            limit=10,
            exclude_message_id=event.id,
        )
    )

    link_count = detection.count_links(
        text
    )

    char_flood = detection.has_char_flood(
        text
    )

    features = build_features(
        text=text,
        repeat_count=repeat_count,
        recent_message_count=recent_message_count,
        recent_texts=recent_texts,
        link_count=link_count,
        char_flood=char_flood,
        flood_threshold=settings[
            "flood_count"
        ],
        repeat_threshold=settings[
            "max_repeat"
        ],
        link_threshold=settings[
            "max_links"
        ],
    )

    external_signals = {}

    await self.event_bus.emit(
        "spam_signals",
        event=event,
        group_id=event.chat_id,
        user_id=event.sender_id,
        signals=external_signals,
    )

    preliminary_score = calculate_score(
        features
    )

    await self.context.record_first_seen(
        event.chat_id,
        event.sender_id,
    )

    has_bio_rules = await self.rules.has_bio_rules(
        event.chat_id
    )

    # پیام لینک‌دار را هم حتماً Context می‌کنیم
    # تا لینک پروفایل web.splus.ir فرصت اثرگذاری داشته باشد.
    if (
        preliminary_score >= 20
        or link_count > 0
        or external_signals.get(
            "content_filter_match"
        )
        or external_signals.get(
            "hard_spam"
        )
        or has_bio_rules
    ):
        context = await self.context.collect(
            event,
            external_signals,
        )

    else:
        context = {
            "join_age_seconds": None,
            "is_new_user": False,
            "profile_has_link": False,
            "profile_has_splus_web_link": False,
            "profile_has_splus_meet_link": False,
            "profile_has_other_link": False,
            "matched_bio_rules": [],
            "external_signals": external_signals,
        }

    decision = decide(
        features=features,
        context=context,
    )

    if decision.level == "NORMAL":
        return

    cached_admin = self.admin_cache.get(
        event.chat_id,
        event.sender_id,
    )

    if cached_admin is None:
        try:
            chat = await event.get_chat()

            cached_admin = await is_chat_admin(
                self.client,
                chat,
                event.sender_id,
                raise_on_error=True,
            )

            self.admin_cache.set(
                event.chat_id,
                event.sender_id,
                cached_admin,
            )

        except Exception:
            # اگر وضعیت ادمین مشخص نیست، مجازات نکن.
            return

    if cached_admin:
        self.tracker.clear_user(
            event.chat_id,
            event.sender_id,
        )
        return

    await apply_decision(
        self,
        event,
        decision,
        features,
        context,
        settings["flood_seconds"],
    )


@on_bus_event("spam_suspicious")
async def on_spam_suspicious(
    self: "SpamFilterPlugin",
    event,
    group_id: int,
    user_id: int,
    score: int,
    reason: str,
    hard_rule: str | None,
    features,
    context: dict,
) -> None:
    self.telemetry.add(
        group_id=group_id,
        user_id=user_id,
        score=score,
        reason=reason,
        hard_rule=hard_rule,
    )


@on_event(events.ChatAction)
async def on_member_change(
    self: "SpamFilterPlugin",
    event,
) -> None:
    if not getattr(
        event,
        "is_group",
        False,
    ):
        return

    user_id = getattr(
        event,
        "user_id",
        None,
    )

    if user_id is None:
        return

    if getattr(
        event,
        "user_joined",
        False,
    ):
        await self.context.record_join(
            event.chat_id,
            user_id,
        )

    elif getattr(
        event,
        "user_left",
        False,
    ):
        await self.context.record_leave(
            event.chat_id,
            user_id,
        )