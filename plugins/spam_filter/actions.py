from .engine import (
    SpamDecision,
    SpamFeatures,
    calculate_violation_score,
)


async def _delete_messages(
    self,
    event,
    message_ids: list[int],
) -> None:
    if not message_ids:
        return

    try:
        chat = await event.get_chat()

        await self.client.delete_messages(
            chat,
            message_ids,
        )

    except Exception as exc:
        print(
            f"⚠️ نتونستم پیام‌های اسپم رو پاک کنم: {exc}"
        )

def _get_spam_type(
    decision: SpamDecision,
    features: SpamFeatures,
) -> str:
    if decision.hard_rule == "custom_text_rule":
        return "قانون سفارشی"

    if decision.hard_rule == "external_hard_spam":
        return "قانون خارجی"

    if decision.hard_rule == "content_filter_plus_spam":
        return "محتوای ممنوع"

    if decision.hard_rule == "flood_plus_repetition":
        return "فلاد و پیام تکراری"

    signals = [
        (
            features.flood_score,
            "فلاد",
        ),
        (
            features.repeat_score,
            "پیام تکراری",
        ),
        (
            features.similarity_score,
            "پیام‌های مشابه",
        ),
        (
            features.char_flood_score,
            "تکرار بیش از حد کاراکتر",
        ),
    ]

    score, reason = max(
        signals,
        key=lambda item: item[0],
    )

    if score > 0:
        return reason

    return "الگوی اسپم"

async def apply_decision(
    self,
    event,
    decision: SpamDecision,
    features: SpamFeatures,
    context: dict,
    delete_window_seconds: int,
) -> None:

    confirmation = (
        self.confirmation.observe(
            event.chat_id,
            event.sender_id,
            decision,
            features,
        )
    )

    # ---------------------------------------------
    # فقط مشکوک:
    # هیچ حذف/مجازاتی
    # ---------------------------------------------

    if decision.level == "SUSPICIOUS":

        self.telemetry.add(
            group_id=event.chat_id,
            user_id=event.sender_id,
            score=decision.score,
            reason=decision.reason,
            hard_rule=decision.hard_rule,
        )

        return

    external = context.get(
        "external_signals",
        {},
    )

    # ---------------------------------------------
    # SPAM
    # ---------------------------------------------

    if decision.level == "SPAM":

        await _delete_messages(
            self,
            event,
            [event.id],
        )

    # ---------------------------------------------
    # HARD_SPAM
    # ---------------------------------------------

    elif decision.level == "HARD_SPAM":

        ids = self.tracker.ids_in_window(
            event.chat_id,
            event.sender_id,
            delete_window_seconds,
        )

        if event.id not in ids:
            ids.append(event.id)

        await _delete_messages(
            self,
            event,
            ids,
        )

        self.tracker.clear_user(
            event.chat_id,
            event.sender_id,
        )

    else:
        return

    # ---------------------------------------------
    # هنوز مطمئن نیستیم
    # پیام حذف شد ولی مجازات نداریم.
    # ---------------------------------------------

    if not confirmation.confirmed_now:
        return

    # ---------------------------------------------
    # Confirmation موفق شد.
    #
    # از اینجا به بعد این واقعاً یک violation
    # قابل مجازات است.
    # ---------------------------------------------

    violation_score = max(
        7,
        calculate_violation_score(
            decision
        ),
    )

    await self.event_bus.emit(
        "violation",
        event=event,
        group_id=event.chat_id,
        user_id=event.sender_id,
        reason=(
            f"رفتار اسپمی تأیید شد: "
            f"{confirmation.reason}"
        ),
        spam_type=_get_spam_type(
            decision,
            features,
        ),
        violation_score=violation_score,
        confidence=confirmation.confidence,
        source="spam_filter",
        message_ids=(
            [event.id]
            if decision.level == "SPAM"
            else ids
        ),
    )