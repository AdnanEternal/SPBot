from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import (
    command,
    on_bus_event,
    on_event,
)
from core.permissions import is_chat_admin

from . import detection
from .actions import apply_decision
from .engine import (
    build_features,
    calculate_score,
    decide,
)

if TYPE_CHECKING:
    from .plugin import SpamFilterPlugin


def _is_remote_group_id(
    value: str,
) -> bool:
    try:
        return int(value) < 0
    except (TypeError, ValueError):
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
    target_group, args = (
        _resolve_spam_group_target(event)
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    if not args.isdigit():
        await event.reply(
            "❌ شناسه کاربر باید عددی باشد."
        )
        return

    added = await self.whitelist.add(
        target_group,
        int(args),
    )

    if not added:
        await event.reply(
            "ℹ️ کاربر از قبل معاف است."
        )
        return

    await event.reply(
        f"✅ کاربر `{args}` معاف شد."
    )


@command(
    name="اسپم رفع معافیت",
    permission="admin",
    chat_type="all",
    description="معافیت کاربر را حذف می‌کند.",
)
async def remove_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = (
        _resolve_spam_group_target(event)
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    if not args.isdigit():
        await event.reply(
            "❌ شناسه کاربر باید عددی باشد."
        )
        return

    removed = await self.whitelist.remove(
        target_group,
        int(args),
    )

    if not removed:
        await event.reply(
            "❌ کاربر در whitelist نبود."
        )
        return

    await event.reply(
        f"✅ معافیت `{args}` حذف شد."
    )


@command(
    name="اسپم معاف ها",
    permission="admin",
    chat_type="all",
    description="لیست کاربران معاف را نشان می‌دهد.",
)
async def list_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = (
        _resolve_spam_group_target(event)
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

    users = await self.whitelist.get_all(
        target_group
    )

    if not users:
        await event.reply(
            "📋 لیست معافیت خالی است."
        )
        return

    await event.reply(
        "📋 کاربران معاف:\n\n"
        + "\n".join(
            f"• `{user_id}`"
            for user_id in users
        )
    )


@command(
    name="اسپم فلاد",
    permission="admin",
    chat_type="group",
    description="تنظیم فلاد.",
)
async def set_flood(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    parts = event.args_text.split()

    if (
        len(parts) != 2
        or not all(
            part.isdigit()
            for part in parts
        )
    ):
        await event.reply(
            "مثال: !اسپم فلاد 5 10"
        )
        return

    count = int(parts[0])
    seconds = int(parts[1])

    await self.settings.set_flood(
        event.chat_id,
        count,
        seconds,
    )

    await event.reply(
        f"✅ فلاد: بیشتر از {count} پیام "
        f"در {seconds} ثانیه."
    )


@command(
    name="اسپم تکرار",
    permission="admin",
    chat_type="group",
    description="تنظیم تکرار.",
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
        f"✅ حداکثر تکرار روی {value} تنظیم شد."
    )


@command(
    name="تنظیمات اسپم",
    permission="admin",
    chat_type="group",
    description="تنظیمات Spam Filter.",
)
async def show_settings(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    settings = await self.settings.get(
        event.chat_id
    )

    await event.reply(
        "⚙️ تنظیمات Spam Filter:\n\n"
        f"فلاد: بیشتر از "
        f"{settings['flood_count']} پیام در "
        f"{settings['flood_seconds']} ثانیه\n"
        f"تکرار: بیشتر از "
        f"{settings['max_repeat']} پیام یکسان پشت‌سرهم"
    )


@command(
    name="اسپم ممنوع",
    permission="owner",
    chat_type="all",
    description="یک عبارت ممنوع به Rule Engine اضافه می‌کند.",
)
async def add_forbidden_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern = (
        _resolve_spam_group_target(event)
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    pattern = pattern.strip()

    if not pattern:
        await event.reply(
            "❌ عبارت ممنوع مشخص نشده."
        )
        return

    added = await self.rules.add_forbidden(
        target_group,
        pattern,
    )

    if not added:
        await event.reply(
            "ℹ️ این قانون از قبل وجود دارد."
        )
        return

    await event.reply(
        f"✅ عبارت ممنوع اضافه شد:\n"
        f"`{pattern}`\n\n"
        f"اقدام: `HARD_SPAM`"
    )


@command(
    name="اسپم مجاز",
    permission="owner",
    chat_type="all",
    description="یک عبارت را از قوانین ممنوع مستثنی می‌کند.",
)
async def add_allowed_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern = (
        _resolve_spam_group_target(event)
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    pattern = pattern.strip()

    if not pattern:
        await event.reply(
            "❌ عبارت مجاز مشخص نشده."
        )
        return

    added = await self.rules.add_allowed(
        target_group,
        pattern,
    )

    if not added:
        await event.reply(
            "ℹ️ این استثنا از قبل وجود دارد."
        )
        return

    await event.reply(
        f"✅ استثنا اضافه شد:\n"
        f"`{pattern}`"
    )


@command(
    name="اسپم حذف ممنوع",
    permission="owner",
    chat_type="all",
    description="یک قانون ممنوع را حذف می‌کند.",
)
async def remove_forbidden_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern = (
        _resolve_spam_group_target(event)
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    if not pattern.strip():
        await event.reply(
            "❌ عبارت مشخص نشده."
        )
        return

    removed = await self.rules.remove_forbidden(
        target_group,
        pattern,
    )

    if not removed:
        await event.reply(
            "❌ این قانون پیدا نشد."
        )
        return

    await event.reply(
        f"✅ قانون ممنوع حذف شد:\n"
        f"`{pattern}`"
    )


@command(
    name="اسپم حذف مجاز",
    permission="owner",
    chat_type="all",
    description="یک استثنا را حذف می‌کند.",
)
async def remove_allowed_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern = (
        _resolve_spam_group_target(event)
    )

    if target_group is None:
        await event.reply(
            "❌ گروه هدف مشخص نشده."
        )
        return

    if not pattern.strip():
        await event.reply(
            "❌ عبارت مشخص نشده."
        )
        return

    removed = await self.rules.remove_allowed(
        target_group,
        pattern,
    )

    if not removed:
        await event.reply(
            "❌ این استثنا پیدا نشد."
        )
        return

    await event.reply(
        f"✅ استثنا حذف شد:\n"
        f"`{pattern}`"
    )


@command(
    name="اسپم قوانین",
    permission="owner",
    chat_type="all",
    description="تمام قوانین متنی را نشان می‌دهد.",
)
async def list_text_rules(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args = (
        _resolve_spam_group_target(event)
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
        if rule["rule_type"]
        in (
            "text_forbidden",
            "text_allowed",
        )
    ]

    if not rules:
        await event.reply(
            "📋 هیچ Rule متنی ثبت نشده."
        )
        return

    lines = []

    for rule in rules:
        if rule["rule_type"] == "text_forbidden":
            lines.append(
                f"🚫 `{rule['pattern']}` → HARD_SPAM"
            )
        else:
            lines.append(
                f"✅ `{rule['pattern']}` → ALLOW"
            )

    await event.reply(
        "📋 قوانین متنی:\n\n"
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

    char_flood = detection.has_char_flood(
        text
    )

    features = build_features(
        text=text,
        repeat_count=repeat_count,
        recent_message_count=recent_message_count,
        recent_texts=recent_texts,
        char_flood=char_flood,
        flood_threshold=settings[
            "flood_count"
        ],
        repeat_threshold=settings[
            "max_repeat"
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

    has_forbidden_rules = (
        await self.rules.has_forbidden(
            event.chat_id
        )
    )

    if (
        preliminary_score >= 20
        or external_signals.get(
            "content_filter_match"
        )
        or external_signals.get(
            "hard_spam"
        )
        or has_forbidden_rules
    ):
        context = await self.context.collect(
            event,
            external_signals,
        )

    else:
        context = {
            "join_age_seconds": None,
            "is_new_user": False,
            "profile_text": "",
            "matched_text_rules": [],
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