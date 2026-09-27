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

        self.debug(
            "DELETE",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"message_ids={message_ids} "
                "status=success"
            ),
        )

    except Exception as exc:
        self.debug(
            "DELETE",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"message_ids={message_ids} "
                f"status=failed "
                f"error={type(exc).__name__}: {exc}"
            ),
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

    self.debug(
        "CONFIRMATION",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"is_confirmed={confirmation.is_confirmed} "
            f"confirmed_now={confirmation.confirmed_now} "
            f"confidence={confirmation.confidence} "
            f"reason={confirmation.reason}"
        ),
    )

    # ---------------------------------------------
    # SUSPICIOUS:
    # فقط telemetry / evidence
    # هیچ حذف یا مجازاتی
    # ---------------------------------------------

    if decision.level == "SUSPICIOUS":

        trust_state = await self.trust.get(
            event.chat_id,
            event.sender_id,
            context.get(
                "user_origin",
                "UNKNOWN",
            ),
        )

        await self.trust.record_suspicious(
            event.chat_id,
            event.sender_id,
            trust_state,
        )

        self.telemetry.add(
            group_id=event.chat_id,
            user_id=event.sender_id,
            score=decision.score,
            reason=decision.reason,
            hard_rule=decision.hard_rule,
        )

        
    

        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "action=TELEMETRY_ONLY "
                "reason=SUSPICIOUS"
            ),
        )

        return

    # ---------------------------------------------
    # هنوز رفتار به اندازه کافی تأیید نشده
    # بنابراین حتی SPAM هم حذف نمی‌شود.
    # ---------------------------------------------

    if not confirmation.is_confirmed:
        self.telemetry.add(
            group_id=event.chat_id,
            user_id=event.sender_id,
            score=decision.score,
            reason=(
                f"{decision.reason} | "
                "برای تأیید شواهد بیشتری لازم است."
            ),
            hard_rule=decision.hard_rule,
        )

        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"level={decision.level} "
                "action=NONE "
                "reason=NOT_CONFIRMED"
            ),
        )


        return

    # ---------------------------------------------
    # از اینجا به بعد رفتار تأیید شده است.
    # ---------------------------------------------

    ids: list[int] = []

    if decision.level == "SPAM":
        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"level={decision.level} "
                "action=DELETE"
            ),
        )

        await _delete_messages(
            self,
            event,
            [event.id],
        )

    elif decision.level == "HARD_SPAM":

        ids = self.tracker.ids_in_window(
            event.chat_id,
            event.sender_id,
            delete_window_seconds,
        )

        if event.id not in ids:
            ids.append(event.id)

        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"level={decision.level} "
                "action=DELETE"
            ),
        )

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
    # فقط وقتی confirmation در همین incident
    # تازه انجام شده باشد، violation جدید بساز.
    # ---------------------------------------------

    if not confirmation.confirmed_now:
        return

    violation_score = calculate_violation_score(
        decision
    )

    if violation_score <= 0:
        return

    self.debug(
        "VIOLATION",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"severity={violation_score} "
            f"confidence={confirmation.confidence} "
            f"message_ids={(
                [event.id]
                if decision.level == "SPAM"
                else ids
            )}"
        ),
    )

    trust_state = await self.trust.get(
        event.chat_id,
        event.sender_id,
        context.get(
            "user_origin",
            "UNKNOWN",
        ),
    )

    await self.trust.record_violation(
        event.chat_id,
        event.sender_id,
        trust_state,
        violation_score,
    )

    self.debug(
        "TRUST",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"event=VIOLATION "
            f"severity={violation_score} "
            f"trust={trust_state.trust_score:.1f} "
            f"clean_streak={trust_state.clean_streak}"
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