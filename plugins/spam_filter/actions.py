from .engine import SpamDecision, SpamFeatures


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


async def apply_decision(
    self,
    event,
    decision: SpamDecision,
    features: SpamFeatures,
    context: dict,
    delete_window_seconds: int,
) -> None:
    if decision.level == "NORMAL":
        return

    if decision.level == "SUSPICIOUS":
        await self.event_bus.emit(
            "spam_suspicious",
            event=event,
            group_id=event.chat_id,
            user_id=event.sender_id,
            score=decision.score,
            reason=decision.reason,
            features=features,
            context=context,
        )
        return

    content_filter_match = context.get(
        "external_signals",
        {},
    ).get(
        "content_filter_match",
        False,
    )

    if decision.level == "SPAM":
        await _delete_messages(
            self,
            event,
            [event.id],
        )

        # اگر Content Filter هم match کرده،
        # خودش violation را ثبت خواهد کرد.
        if not content_filter_match:
            await self.event_bus.emit(
                "violation",
                event=event,
                group_id=event.chat_id,
                user_id=event.sender_id,
                reason=(
                    f"اسپم: {decision.reason} "
                    f"(score={decision.score}/100)"
                ),
                message_ids=[
                    event.id
                ],
            )

        return

    if decision.level == "HARD_SPAM":
        ids = self.tracker.ids_in_window(
            event.chat_id,
            event.sender_id,
            delete_window_seconds,
        )

        if not ids:
            ids = [event.id]

        await _delete_messages(
            self,
            event,
            ids,
        )

        self.tracker.clear_user(
            event.chat_id,
            event.sender_id,
        )

        if not content_filter_match:
            await self.event_bus.emit(
                "violation",
                event=event,
                group_id=event.chat_id,
                user_id=event.sender_id,
                reason=(
                    f"اسپم شدید: {decision.reason} "
                    f"(score={decision.score}/100)"
                ),
                message_ids=ids,
            )