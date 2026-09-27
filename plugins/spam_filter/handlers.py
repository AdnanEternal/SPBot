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
    adaptive_flood_threshold,
    build_features,
    calculate_score,
    decide,
)

from .trust import (
    classify_user_state,
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

    key = (
        event.chat_id,
        event.sender_id,
    )

    if await self.whitelist.is_exempt(
        event.chat_id,
        event.sender_id,
    ):
        self.debug(
            "SKIP",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "reason=whitelisted"
            ),
        )
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

    await self.context.record_first_seen(
        event.chat_id,
        event.sender_id,
    )

    join_age_seconds, user_origin = (
        await self.context.get_membership_context(
            event.chat_id,
            event.sender_id,
        )
    )

    trust_state = await self.trust.get(
        event.chat_id,
        event.sender_id,
        user_origin,
    )

    user_state = classify_user_state(
        join_age_seconds=join_age_seconds,
        origin=user_origin,
        clean_streak=trust_state.clean_streak,
    )

    is_new_user = (
        user_state == "NEW"
    )
    age_state = (
        "UNKNOWN"
        if join_age_seconds is None
        else (
            "NEW"
            if join_age_seconds <= 24 * 3600
            else "KNOWN"
        )
    )

    previous_age_state = (
        self._debug_last_age_state.get(key)
    )

    if previous_age_state != age_state:
        age_text = (
            "unknown"
            if join_age_seconds is None
            else f"{join_age_seconds:.1f}s"
        )

        self.debug(
            "USER",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"state={user_state} "
                f"origin={user_origin} "
                f"age={(
                    'unknown'
                    if join_age_seconds is None
                    else f'{join_age_seconds:.1f}s'
                )} "
                f"trust={trust_state.trust_score:.1f} "
                f"clean_streak={trust_state.clean_streak} "
                f"clean_messages={trust_state.clean_messages}"
            ),
        )

        self._debug_last_age_state[key] = (
            age_state
        )

    base_flood_threshold = settings[
        "flood_count"
    ]

    flood_threshold = adaptive_flood_threshold(
        base_flood_threshold,
        join_age_seconds,
        trust_score=trust_state.trust_score,
        user_origin=user_origin,
        is_new_user=is_new_user,
    )

    burst_message_count = (
        self.tracker.count_in_window(
            event.chat_id,
            event.sender_id,
            3,
        )
    )

    features = build_features(
        text=text,
        repeat_count=repeat_count,
        recent_message_count=recent_message_count,
        recent_texts=recent_texts,
        burst_message_count=burst_message_count,
        char_flood=char_flood,
        flood_threshold=flood_threshold,
        repeat_threshold=settings[
            "max_repeat"
        ],
    )

    self.debug(
        "USER",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"state={user_state} "
            f"origin={user_origin} "
            f"age={(
                'unknown'
                if join_age_seconds is None
                else f'{join_age_seconds:.1f}s'
            )} "
            f"trust={trust_state.trust_score:.1f} "
            f"clean_streak={trust_state.clean_streak} "
            f"clean_messages={trust_state.clean_messages}"
        ),
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
        features,
        {
            "join_age_seconds": join_age_seconds,
            "is_new_user": (
                join_age_seconds is not None
                and join_age_seconds <= 24 * 3600
            ),
            "external_signals": external_signals,
        },
    )

    has_forbidden_rules = (
        await self.rules.has_forbidden(
            event.chat_id
        )
    )

    needs_context = (
        preliminary_score >= 20
        or external_signals.get(
            "content_filter_match"
        )
        or external_signals.get(
            "hard_spam"
        )
        or has_forbidden_rules
    )

    self.debug(
        "CONTEXT",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"preliminary_score={preliminary_score} "
            f"load_full_context={bool(needs_context)}"
        ),
    )

    if needs_context:
        context = await self.context.collect(
            event,
            external_signals,
        )

        context["join_age_seconds"] = (
            join_age_seconds
        )

        context["is_new_user"] = (
            join_age_seconds is not None
            and join_age_seconds <= 24 * 3600
        )

    else:
        context = {
            "join_age_seconds": join_age_seconds,
            "is_new_user": (
                join_age_seconds is not None
                and join_age_seconds <= 24 * 3600
            ),
            "profile_text": "",
            "matched_text_rules": [],
            "external_signals": external_signals,
        }

    context["flood_threshold"] = (
        flood_threshold
    )
    context["base_flood_threshold"] = (
        base_flood_threshold
    )
    
    context["user_origin"] = user_origin
    context["user_state"] = user_state
    context["trust_score"] = (
        trust_state.trust_score
    )
    context["clean_streak"] = (
        trust_state.clean_streak
    )


    decision = decide(
        features=features,
        context=context,
    )

    self.debug(
        "DECISION",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"message={event.id} "
            f"level={decision.level} "
            f"score={decision.score} "
            f"hard_rule={decision.hard_rule or '-'} "
            f"reason={decision.reason or '-'}"
        ),
    )

    previous_status = (
        self._debug_last_status.get(key)
    )

    if (
        previous_status == "SUSPICIOUS"
        and decision.level == "NORMAL"
    ):
        self.debug(
            "STATE",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "transition=SUSPICIOUS->NORMAL"
            ),
        )

    elif (
        previous_status is not None
        and previous_status != decision.level
    ):
        self.debug(
            "STATE",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"transition={previous_status}"
                f"->{decision.level}"
            ),
        )

    self._debug_last_status[key] = (
        decision.level
    )

    if decision.level == "SUSPICIOUS":
        self.debug(
            "SUSPICIOUS",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"score={decision.score} "
                f"hard_rule={decision.hard_rule or '-'}"
            ),
        )

    elif decision.level == "HARD_SPAM":
        self.debug(
            "HARD_SPAM",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"score={decision.score} "
                f"hard_rule={decision.hard_rule or '-'}"
            ),
        )

    elif decision.level == "SPAM":
        self.debug(
            "SPAM",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"score={decision.score} "
                f"hard_rule={decision.hard_rule or '-'}"
            ),
        )

    if decision.level == "NORMAL":
        await self.trust.record_clean(
            event.chat_id,
            event.sender_id,
            trust_state,
        )

        return

    try:
        chat = await event.get_chat()

        is_admin = await is_chat_admin(
            self.client,
            chat,
            event.sender_id,
            raise_on_error=True,
        )

    except Exception as exc:
        self.debug(
            "ADMIN_CHECK",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"status=FAILED "
                f"error={type(exc).__name__}"
            ),
        )
        return

    if is_admin:
        self.debug(
            "SKIP",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "reason=admin"
            ),
        )

        self.tracker.clear_user(
            event.chat_id,
            event.sender_id,
        )
        return

    self.debug(
        "ACTION",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"level={decision.level} "
            "status=apply_decision"
        ),
    )

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