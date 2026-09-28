from .engine import (
    SpamDecision,
    SpamFeatures,
    calculate_violation_score,
)

async def _delete_messages(
    self,
    event,
    message_ids: list[int],
) -> bool:
    if not message_ids:
        return False

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

        return True

    except Exception as exc:
        self.debug(
            "DELETE",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                f"message_ids={message_ids} "
                "status=failed "
                f"error_type={type(exc).__name__}"
            ),
        )

        return False
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

    # Content Filter قبلاً این پیام را مدیریت کرده است.
    if decision.hard_rule == (
        "content_filter_plus_spam"
    ):
        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "action=NONE "
                "reason=CONTENT_FILTER_ALREADY_HANDLED"
            ),
        )
        return

    # Rule متنی مالک مستقل از تشخیص spammer است.
    if decision.hard_rule == (
        "custom_text_rule"
    ):
        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "level=CUSTOM_RULE "
                "action=DELETE"
            ),
        )

        deleted = await _delete_messages(
            self,
            event,
            [event.id],
        )

        if not deleted:
            self.debug(
                "ACTION",
                (
                    f"group={event.chat_id} "
                    f"user={event.sender_id} "
                    "status=STOPPED "
                    "reason=CUSTOM_RULE_DELETE_FAILED"
                ),
            )

        return

    confirmation = (
        self.confirmation.observe(
            event.chat_id,
            event.sender_id,
            decision,
            features,
        )
    )

    if confirmation.confirmed_now:
        confirmation_code = (
            decision.hard_rule
            or "multi_signal_confirmation"
        )

    elif confirmation.is_confirmed:
        confirmation_code = (
            "existing_confirmation"
        )

    else:
        confirmation_code = (
            "insufficient_evidence"
        )

    self.debug(
        "CONFIRMATION",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"is_confirmed={confirmation.is_confirmed} "
            f"confirmed_now={confirmation.confirmed_now} "
            f"confidence={confirmation.confidence} "
            f"code={confirmation_code}"
        ),
    )

    # ---------------------------------------------
    # SUSPICIOUS = فقط telemetry/trust
    # ---------------------------------------------

    if decision.level == "SUSPICIOUS":

        updated_trust = (
            await self.trust.record_suspicious(
                event.chat_id,
                event.sender_id,
            )
        )

        self.debug(
            "TRUST",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "event=SUSPICIOUS "
                f"trust={updated_trust.trust_score:.1f} "
                f"clean_streak={updated_trust.clean_streak} "
                f"suspicious_events="
                f"{updated_trust.suspicious_events}"
            ),
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
    # هنوز ثابت نشده که کاربر اسپمر است.
    # هیچ پیامی حذف نشود.
    # ---------------------------------------------

    if not confirmation.is_confirmed:

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
                f"level={decision.level} "
                "action=NONE "
                "reason=NOT_CONFIRMED"
            ),
        )

        return

    # ---------------------------------------------
    # از اینجا به بعد کاربر واقعاً confirmed است.
    # ---------------------------------------------

    ids: list[int] = []
    deleted = False

    if decision.level == "SPAM":

        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "level=SPAM "
                "action=DELETE"
            ),
        )

        deleted = await _delete_messages(
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
                "level=HARD_SPAM "
                "action=DELETE "
                f"count={len(ids)}"
            ),
        )

        deleted = await _delete_messages(
            self,
            event,
            ids,
        )

        if deleted:
            self.tracker.clear_user(
                event.chat_id,
                event.sender_id,
            )

    else:
        return

    if not deleted:
        self.debug(
            "ACTION",
            (
                f"group={event.chat_id} "
                f"user={event.sender_id} "
                "status=STOPPED "
                "reason=DELETE_FAILED"
            ),
        )
        return

    # فقط همان لحظه‌ای که confirmation حاصل شده
    # violation جدید ثبت کن.
    if not confirmation.confirmed_now:
        return

    violation_score = calculate_violation_score(
        decision,
        context,
    )

    if violation_score <= 0:
        return

    updated_trust = (
        await self.trust.record_violation(
            event.chat_id,
            event.sender_id,
            violation_score,
        )
    )

    self.debug(
        "VIOLATION",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"severity={violation_score} "
            f"confidence={confirmation.confidence}"
        ),
    )

    self.debug(
        "TRUST",
        (
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            "event=VIOLATION "
            f"severity={violation_score} "
            f"trust={updated_trust.trust_score:.1f} "
            f"clean_streak={updated_trust.clean_streak} "
            f"violation_count="
            f"{updated_trust.violation_count}"
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