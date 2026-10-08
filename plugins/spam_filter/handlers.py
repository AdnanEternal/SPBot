from typing import TYPE_CHECKING

from splusthon import events

from core.decorators import (
    command,
    on_bus_event,
    on_event,
)


from core.permissions import is_chat_admin, is_owner

from . import detection
from .actions import (
    apply_decision,
    apply_repeat_only_intervention,
)
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


async def _resolve_spam_group_target(
    event,
) -> tuple[int | None, str, bool]:
    raw = (
        event.args_text or ""
    ).strip()

    target_group, clean_args = (
        _extract_optional_group_target(
            raw
        )
    )

    # -------------------------------------------------
    # REMOTE GROUP
    # -------------------------------------------------

    if target_group is not None:

        if not is_owner(
            event.sender_id
        ):
            await event.reply(
                "❌ اجرای ریموت این کامند فقط "
                "برای Owner مجازه."
            )

            return (
                None,
                clean_args,
                True,
            )

        return (
            target_group,
            clean_args,
            False,
        )

    # -------------------------------------------------
    # LOCAL GROUP
    # -------------------------------------------------

    if event.is_group:
        return (
            event.chat_id,
            clean_args,
            False,
        )

    return (
        None,
        clean_args,
        False,
    )

@command(
    name="اسپم رفع معافیت",
    permission="admin",
    chat_type="all",
    description="معافیت کاربر را حذف می‌کند.",
    native_name="spam_unexempt",
)
async def remove_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args, remote_denied= (
        await _resolve_spam_group_target(event)
    )

    if remote_denied:
        return

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
    name="اسپم معاف",
    permission="admin",
    chat_type="all",
    description="یک کاربر را از Spam Filter معاف می‌کند.",
    native_name="spam_exempt",
)
async def add_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args, remote_denied = (
        await _resolve_spam_group_target(event)
    )
    
    if remote_denied:
        return

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
    name="اسپم معاف ها",
    permission="admin",
    chat_type="all",
    description="لیست کاربران معاف را نشان می‌دهد.",
    native_name="spam_exemptions",
)
async def list_whitelist(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args, remote_denied = (
        await _resolve_spam_group_target(event)
    )
    
    if remote_denied:
        return
    
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
    native_name="spam_flood",
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
            "مثال: "
            + self.command_usage(
                event.command,
                "5 10",
                event=event,
            )
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
    native_name="spam_repeat",
)
async def set_max_repeat(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    value = event.args_text.strip()

    if not value.isdigit():
        await event.reply(
            "مثال: "
            + self.command_usage(
                event.command,
                "3",
                event=event,
            )
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
    native_name="spam_settings",
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
    native_name="spam_forbidden_add",
)
async def add_forbidden_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern, remote_denied = (
        await _resolve_spam_group_target(event)
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
        f"اقدام: `حذف پیام`"
    )


@command(
    name="اسپم مجاز",
    permission="owner",
    chat_type="all",
    description="یک عبارت را از قوانین ممنوع مستثنی می‌کند.",
    native_name="spam_allowed_add",
)
async def add_allowed_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern, remote_denied= (
        await _resolve_spam_group_target(event)
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
    native_name="spam_forbidden_remove",
)
async def remove_forbidden_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern, remote_denied= (
        await _resolve_spam_group_target(event)
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
    native_name="spam_allowed_remove",
)
async def remove_allowed_rule(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, pattern, remote_denied= (
        await _resolve_spam_group_target(event)
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
    native_name="spam_rules",
)
async def list_text_rules(
    self: "SpamFilterPlugin",
    event: events.NewMessage.Event,
) -> None:
    target_group, args, remote_denied= (
        await _resolve_spam_group_target(event)
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
    
    event_timestamp = event.date.timestamp()

    repeat_count = self.tracker.register(
        event.chat_id,
        event.sender_id,
        event.id,
        text,
        event_timestamp,
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
    )

    user_state = classify_user_state(
        join_age_seconds=join_age_seconds,
        origin=user_origin,
        clean_streak=trust_state.clean_streak,
    )

    previous_user_state = (
        self._debug_last_user_state.get(key)
    )

    if (
        previous_user_state is not None
        and previous_user_state != user_state
    ):
        self.debug(
            "USER_STATE",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"transition={previous_user_state}"
                f"->{user_state}"
            ),
        )

    self._debug_last_user_state[key] = (
        user_state
    )

    previous_origin = (
        self._debug_last_origin.get(key)
    )

    if (
        previous_origin is not None
        and previous_origin != user_origin
    ):
        self.debug(
            "USER_ORIGIN",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"transition={previous_origin}"
                f"->{user_origin}"
            ),
        )

    self._debug_last_origin[key] = (
        user_origin
    )

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
            f"age={age_text} "
            f"trust={trust_state.trust_score:.1f} "
            f"clean_streak={trust_state.clean_streak} "
            f"clean_messages={trust_state.clean_messages}"
        ),
    )

    is_new_user = (
        user_state == "NEW"
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
        "METRICS",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"message={event.id} "
            f"recent={recent_message_count} "
            f"burst={burst_message_count} "
            f"repeat={repeat_count} "
            f"flood_score={features.flood_score} "
            f"burst_score={features.burst_score} "
            f"repeat_score={features.repeat_score} "
            f"similarity_score={features.similarity_score} "
            f"char_flood_score={features.char_flood_score} "
            f"flood_threshold={flood_threshold} "
            f"trust={trust_state.trust_score:.1f}"
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
            "is_new_user": is_new_user,
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
            is_new_user
        )

    else:
        context = {
            "join_age_seconds": join_age_seconds,
            "is_new_user": is_new_user,
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

    context["user_origin"] = (
        user_origin
    )

    context["user_state"] = (
        user_state
    )

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

    if decision.hard_rule:
        reason_code = (
            decision.hard_rule
        )

    elif decision.level == "SUSPICIOUS":
        reason_code = (
            "score_suspicious_threshold"
        )

    elif decision.level == "SPAM":
        reason_code = (
            "score_spam_threshold"
        )

    elif decision.level == "HARD_SPAM":
        reason_code = (
            "score_hard_threshold"
        )

    else:
        reason_code = "no_spam_signal"

    self.debug(
        "DECISION",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"message={event.id} "
            f"level={decision.level} "
            f"score={decision.score} "
            f"hard_rule={decision.hard_rule or '-'} "
            f"reason_code={reason_code}"
        ),
    )

    # -------------------------------------------------
    # Repeat-only intervention
    #
    # فقط وقتی Repeat تنها رفتار مسئله‌دار است.
    # در این مرحله decision و context و features
    # همگی ساخته شده‌اند.
    #
    # ادمین/مالک هم در این مسیر هشدار می‌گیرد،
    # ولی مجازات نمی‌شود.
    # -------------------------------------------------

    repeat_only = (
        decision.hard_rule is None
        and features.repeat_score > 0
        and features.flood_score == 0
        and features.burst_score == 0
        and features.similarity_score == 0
        and features.char_flood_score == 0
    )

    if repeat_only:
        try:
            repeat_is_admin = await is_chat_admin(
                self.client,
                await event.get_chat(),
                event.sender_id,
                raise_on_error=True,
            )

        except Exception as exc:
            # در صورت شکست بررسی ادمین،
            # مسیر penalty را غیرفعال می‌کنیم.
            repeat_is_admin = True

            self.debug(
                "ADMIN_CHECK",
                (
                    f"group={event.chat_id} "
                    f"user={event.sender_id} "
                    "status=FAILED_REPEAT_ONLY "
                    f"error_type={type(exc).__name__}"
                ),
            )

        handled = (
            await apply_repeat_only_intervention(
                self,
                event,
                features,
                context,
                repeat_is_admin,
                settings["max_repeat"],
            )
        )

        if handled:
            return


    previous_status = (
        self._debug_last_status.get(key)
    )

    if (
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

    if decision.level == "NORMAL":
    # A message can be NORMAL while still carrying weak spam evidence.
    # Such a message must not be rewarded as CLEAN.
        if preliminary_score > 0:
            self.debug(
                "TRUST",
                (
                    f"group={event.chat_id} "
                    f"user={event.sender_id} "
                    "event=NEUTRAL "
                    "reason=behavioral_evidence "
                    f"score={preliminary_score}"
                ),
            )
            return

        updated_trust = (
            await self.trust.record_clean(
                event.chat_id,
                event.sender_id,
            )
        )

        new_user_state = (
            classify_user_state(
                join_age_seconds=join_age_seconds,
                origin=user_origin,
                clean_streak=(
                    updated_trust.clean_streak
                ),
            )
        )

        if new_user_state != user_state:
            self.debug(
                "USER_STATE",
                (
                    f"group={event.chat_id} "
                    f"user={event.sender_id} "
                    f"transition={user_state}"
                    f"->{new_user_state} "
                    "trigger=clean_activity"
                ),
            )

            self._debug_last_user_state[key] = (
                new_user_state
            )

        self.debug(
            "TRUST",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "event=CLEAN "
                f"trust={updated_trust.trust_score:.1f} "
                f"clean_streak={updated_trust.clean_streak} "
                f"clean_messages={updated_trust.clean_messages}"
            ),
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
                "status=FAILED "
                f"error_type={type(exc).__name__}"
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

    key = (
        event.chat_id,
        user_id,
    )

    joined = (
        getattr(
            event,
            "user_joined",
            False,
        )
        or getattr(
            event,
            "user_added",
            False,
        )
    )

    left = (
        getattr(
            event,
            "user_left",
            False,
        )
        or getattr(
            event,
            "user_kicked",
            False,
        )
    )

    if joined:

        # عضویت جدید باید با تاریخچه‌ی رفتاری
        # قبلی قاطی نشود.
        self.tracker.clear_user(
            event.chat_id,
            user_id,
        )

        self.confirmation.clear(
            event.chat_id,
            user_id,
        )

        await self.context.record_join(
            event.chat_id,
            user_id,
        )

        await self.trust.reset_clean_streak(
            event.chat_id,
            user_id,
        )

        self._debug_last_status.pop(
            key,
            None,
        )

        self._debug_last_user_state.pop(
            key,
            None,
        )

        self._debug_last_origin.pop(
            key,
            None,
        )

        self.debug(
            "MEMBER",
            (
                f"group={event.chat_id} "
                f"user={user_id} "
                "event=JOIN"
            ),
        )

    elif left:

        # بعد از خروج، پیام‌های قبلی نباید
        # در Flood/Repeat عضویت بعدی دخالت کنند.
        self.tracker.clear_user(
            event.chat_id,
            user_id,
        )

        self.confirmation.clear(
            event.chat_id,
            user_id,
        )

        await self.context.record_leave(
            event.chat_id,
            user_id,
        )

        self._debug_last_status.pop(
            key,
            None,
        )

        self._debug_last_user_state.pop(
            key,
            None,
        )

        self._debug_last_origin.pop(
            key,
            None,
        )

        self.debug(
            "MEMBER",
            (
                f"group={event.chat_id} "
                f"user={user_id} "
                "event=LEAVE"
            ),
        )