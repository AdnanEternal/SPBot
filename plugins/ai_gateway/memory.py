from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

from litellm import token_counter


class AIMemoryManager:
    KEEP_MESSAGES = 1000
    MESSAGE_OVERHEAD_TOKENS = 4
    TRIM_EVERY_MESSAGES = 50

    # -----------------------------
    # Timeline
    # -----------------------------

    MAX_TIMELINE_MESSAGES = 1000
    TIMELINE_CONTEXT_MESSAGES = 80
    TIMELINE_CONTEXT_CHARS = 12000

    def __init__(self, store, settings_store):
        self.store = store
        self.settings = settings_store

        self._trim_counters = defaultdict(int)

        # group_id -> deque of timeline records
        self._timelines: dict[
            int,
            deque[dict[str, Any]],
        ] = {}

        # group_id -> set(message_id)
        # برای جلوگیری از ثبت دوباره‌ی یک پیام
        self._timeline_seen: dict[
            int,
            set[int],
        ] = {}

        # group_id -> {user_id: display_name}
        self._timeline_sender_cache: dict[
            int,
            dict[int, str],
        ] = {}

    # =========================================================
    # Existing memory system
    # =========================================================

    async def maybe_trim(
        self,
        group_id: int,
    ) -> None:
        self._trim_counters[group_id] += 1

        if self._trim_counters[group_id] < self.TRIM_EVERY_MESSAGES:
            return

        self._trim_counters[group_id] = 0

        await self.trim(group_id)

    def _select_messages(
        self,
        rows: list[dict],
        system_prompt: str,
        token_limit: int,
        model_name: str | None,
    ) -> list[dict[str, str]]:
        """
        پیام‌ها را از جدیدترین به قدیمی‌ترین انتخاب می‌کند
        تا سقف توکن پر شود.
        """

        counter_ok = model_name is not None

        def count(text: str) -> int:
            nonlocal counter_ok

            if counter_ok:
                try:
                    return (
                        int(
                            token_counter(
                                model=model_name,
                                text=text,
                            )
                        )
                        + self.MESSAGE_OVERHEAD_TOKENS
                    )
                except Exception as exc:
                    print(
                        f"⚠️ خطا در محاسبه توکن حافظه: {exc}"
                    )
                    counter_ok = False

            return (
                max(1, len(text) // 4)
                + self.MESSAGE_OVERHEAD_TOKENS
            )

        total = count(system_prompt)
        selected: list[dict[str, str]] = []

        for row in reversed(rows):
            cost = count(row["content"])

            if selected and total + cost > token_limit:
                break

            selected.append(
                {
                    "role": row["role"],
                    "content": row["content"],
                }
            )

            total += cost

        selected.reverse()

        if (
            selected
            and selected[0]["role"] == "assistant"
        ):
            selected.pop(0)

        return [
            {
                "role": "system",
                "content": system_prompt,
            },
            *selected,
        ]

    # =========================================================
    # Timeline helpers
    # =========================================================

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return "زمان نامشخص"

        try:
            return value.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception:
            return str(value)

    @staticmethod
    def _display_name(
        entity: Any,
        fallback: Any,
    ) -> str:
        if entity is None:
            return str(fallback)

        username = getattr(
            entity,
            "username",
            None,
        )

        first_name = getattr(
            entity,
            "first_name",
            None,
        )

        last_name = getattr(
            entity,
            "last_name",
            None,
        )

        full_name = " ".join(
            part
            for part in (
                first_name,
                last_name,
            )
            if part
        ).strip()

        return (
            username
            or full_name
            or str(fallback)
        )

    @staticmethod
    def _extract_message_id(message: Any) -> int | None:
        value = getattr(
            message,
            "id",
            None,
        )

        if value is None:
            value = getattr(
                message,
                "message_id",
                None,
            )

        if value is None:
            return None

        try:
            return int(value)
        except Exception:
            return None

    async def _extract_reply_id(
        self,
        message: Any,
    ) -> int | None:

        direct = getattr(
            message,
            "reply_to_msg_id",
            None,
        )

        if direct is not None:
            try:
                return int(direct)
            except Exception:
                pass

        reply_to = getattr(
            message,
            "reply_to",
            None,
        )

        if reply_to is not None:
            possible = (
                getattr(
                    reply_to,
                    "reply_to_msg_id",
                    None,
                )
                or getattr(
                    reply_to,
                    "msg_id",
                    None,
                )
            )

            if possible is not None:
                try:
                    return int(possible)
                except Exception:
                    pass

        # fallback مطمئن‌تر برای نسخه‌هایی که
        # reply_to_msg_id را مستقیم expose نمی‌کنند
        try:
            is_reply = bool(
                getattr(
                    message,
                    "is_reply",
                    False,
                )
            )

            if is_reply and hasattr(
                message,
                "get_reply_message",
            ):
                replied = await message.get_reply_message()

                if replied is not None:
                    return self._extract_message_id(
                        replied
                    )

        except Exception:
            pass

        return None

    async def _resolve_sender_name(
        self,
        group_id: int,
        message: Any,
        sender_id: int | None,
    ) -> str:

        if sender_id is None:
            return "نامشخص"

        cache = self._timeline_sender_cache.setdefault(
            group_id,
            {},
        )

        cached = cache.get(sender_id)

        if cached:
            return cached

        sender = None

        try:
            sender = getattr(
                message,
                "sender",
                None,
            )
        except Exception:
            sender = None

        if sender is None:
            try:
                sender = await message.get_sender()
            except Exception:
                sender = None

        name = self._display_name(
            sender,
            sender_id,
        )

        cache[sender_id] = name

        return name

    async def load_timeline(
        self,
        client,
        group_id: int,
        limit: int,
    ) -> int:
        """
        آخرین پیام‌های گروه را از Soroush گرفته
        و در RAM آماده می‌کند.
        """

        limit = max(
            1,
            min(
                int(limit),
                self.MAX_TIMELINE_MESSAGES,
            ),
        )

        messages = await client.get_messages(
            group_id,
            limit=limit,
        )

        if messages is None:
            messages = []

        if not isinstance(
            messages,
            (list, tuple),
        ):
            messages = [messages]

        records: list[dict[str, Any]] = []

        # get_messages معمولاً جدیدترین -> قدیمی‌ترین برمی‌گرداند
        for message in reversed(list(messages)):

            message_id = self._extract_message_id(
                message
            )

            if message_id is None:
                continue

            raw_text = (
                getattr(
                    message,
                    "raw_text",
                    None,
                )
                or getattr(
                    message,
                    "message",
                    None,
                )
                or ""
            )

            text = str(raw_text).strip()

            # کامندها را داخل Timeline ذخیره نمی‌کنیم
            # تا چیزهایی مثل API Key وارد حافظه نشوند.
            if text.startswith("!"):
                continue

            if not text:
                text = "[پیام بدون متن یا رسانه]"

            sender_id = getattr(
                message,
                "sender_id",
                None,
            )

            if sender_id is not None:
                try:
                    sender_id = int(sender_id)
                except Exception:
                    sender_id = None

            sender_name = await self._resolve_sender_name(
                group_id,
                message,
                sender_id,
            )

            reply_to_id = await self._extract_reply_id(
                message
            )

            records.append(
                {
                    "message_id": message_id,
                    "group_id": group_id,
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "text": text,
                    "date": self._format_date(
                        getattr(
                            message,
                            "date",
                            None,
                        )
                    ),
                    "reply_to_id": reply_to_id,
                }
            )

        records = records[-limit:]

        timeline = deque(
            records,
            maxlen=limit,
        )

        self._timelines[group_id] = timeline

        self._timeline_seen[group_id] = {
            int(record["message_id"])
            for record in records
        }

        self._timeline_sender_cache.setdefault(
            group_id,
            {},
        )

        return len(records)

    async def record_event(
        self,
        event,
    ) -> bool:
        """
        پیام جدید را به Timeline اضافه می‌کند.
        اگر Timeline این گروه هنوز load نشده باشد،
        کاری انجام نمی‌دهد.
        """

        group_id = getattr(
            event,
            "chat_id",
            None,
        )

        if group_id is None:
            return False

        if group_id not in self._timelines:
            return False

        message_id = self._extract_message_id(
            event
        )

        if message_id is None:
            return False

        seen = self._timeline_seen.setdefault(
            group_id,
            set(),
        )

        if message_id in seen:
            return False

        raw_text = (
            getattr(
                event,
                "raw_text",
                None,
            )
            or getattr(
                event,
                "message",
                None,
            )
            or ""
        )

        text = str(raw_text).strip()

        # کامندها را ثبت نکن
        if text.startswith("!"):
            return False

        if not text:
            text = "[پیام بدون متن یا رسانه]"

        sender_id = getattr(
            event,
            "sender_id",
            None,
        )

        if sender_id is not None:
            try:
                sender_id = int(sender_id)
            except Exception:
                sender_id = None

        sender_name = "نامشخص"

        if sender_id is not None:
            cache = self._timeline_sender_cache.setdefault(
                group_id,
                {},
            )

            sender_name = cache.get(
                sender_id,
                "",
            )

            if not sender_name:
                try:
                    sender = await event.get_sender()
                except Exception:
                    sender = None

                sender_name = self._display_name(
                    sender,
                    sender_id,
                )

                cache[sender_id] = sender_name

        reply_to_id = await self._extract_reply_id(
            event
        )

        record = {
            "message_id": message_id,
            "group_id": group_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "text": text,
            "date": self._format_date(
                getattr(
                    event,
                    "date",
                    None,
                )
            ),
            "reply_to_id": reply_to_id,
        }

        timeline = self._timelines[group_id]

        if timeline.maxlen is None:
            return False

        if len(timeline) >= timeline.maxlen:
            old = timeline.popleft()

            try:
                seen.discard(
                    int(old["message_id"])
                )
            except Exception:
                pass

        timeline.append(record)
        seen.add(message_id)

        return True

    def clear_timeline(
        self,
        group_id: int,
    ) -> None:
        self._timelines.pop(
            group_id,
            None,
        )

        self._timeline_seen.pop(
            group_id,
            None,
        )

        self._timeline_sender_cache.pop(
            group_id,
            None,
        )

    def clear_all_timelines(self) -> None:
        self._timelines.clear()
        self._timeline_seen.clear()
        self._timeline_sender_cache.clear()

    def has_timeline(
        self,
        group_id: int,
    ) -> bool:
        timeline = self._timelines.get(
            group_id
        )

        return bool(timeline)

    def _format_timeline_record(
        self,
        record: dict[str, Any],
        by_id: dict[int, dict[str, Any]],
    ) -> str:

        text = str(
            record.get(
                "text",
                "",
            )
        ).strip()

        if len(text) > 1200:
            text = text[:1200] + "..."

        result = (
            f"[{record['date']}] "
            f"{record['sender_name']} "
            f"(message_id={record['message_id']}):\n"
            f"{text}"
        )

        reply_to_id = record.get(
            "reply_to_id"
        )

        if reply_to_id is None:
            return result

        target = by_id.get(
            int(reply_to_id)
        )

        if target is None:
            result += (
                "\n↳ در پاسخ به "
                f"message_id={reply_to_id} "
                "(پیام هدف خارج از Timeline فعلی است)"
            )

            return result

        target_text = str(
            target.get(
                "text",
                "",
            )
        ).strip()

        if len(target_text) > 600:
            target_text = (
                target_text[:600]
                + "..."
            )

        result += (
            "\n↳ در پاسخ به "
            f"[{target['date']}] "
            f"{target['sender_name']} "
            f"(message_id={target['message_id']}):\n"
            f"{target_text}"
        )

        return result

    def get_timeline_context(
        self,
        group_id: int,
    ) -> str | None:

        timeline = self._timelines.get(
            group_id
        )

        if not timeline:
            return None

        records = list(timeline)

        by_id = {
            int(record["message_id"]): record
            for record in records
        }

        selected: list[dict[str, Any]] = []

        total_chars = 0

        # از جدیدترین‌ها به عقب می‌رویم.
        for record in reversed(records):

            formatted = self._format_timeline_record(
                record,
                by_id,
            )

            if (
                selected
                and (
                    len(selected)
                    >= self.TIMELINE_CONTEXT_MESSAGES
                    or
                    total_chars + len(formatted)
                    > self.TIMELINE_CONTEXT_CHARS
                )
            ):
                break

            selected.append(record)
            total_chars += len(formatted)

        selected.reverse()

        lines = [
            "🧭 تایم‌لاین اخیر گفتگو:",
            "",
        ]

        for record in selected:
            lines.append(
                self._format_timeline_record(
                    record,
                    by_id,
                )
            )

            lines.append("")

        lines.append(
            "نکته: message_idها برای تشخیص دقیق "
            "رابطه بین پیام‌ها هستند. "
            "↳ یعنی پیام فعلی مستقیماً در پاسخ به "
            "پیام نشان‌داده‌شده ارسال شده است."
        )

        return "\n".join(lines)

    # =========================================================
    # Context building
    # =========================================================

    async def build_context(
        self,
        group_id: int,
        system_prompt: str,
        gateway,
    ) -> list[dict[str, str]]:

        token_limit = await self.settings.get_token_limit(
            group_id
        )

        message_limit = await self.settings.get_message_limit(
            group_id
        )

        rows = await self.store.get_recent(
            group_id,
            message_limit,
        )

        model_name = None

        try:
            model = await gateway.models.get_active()

            if model is not None:
                model_name = gateway._litellm_model(
                    model
                )

        except Exception as exc:
            print(
                "⚠️ خطا در گرفتن مدل فعال "
                f"برای شمارش توکن: {exc}"
            )

        # اگر Timeline فعال باشد، مقداری از بودجه
        # توکن را برای آن کنار می‌گذاریم.
        timeline_context = self.get_timeline_context(
            group_id
        )

        if timeline_context:
            timeline_budget = min(
                2500,
                max(
                    500,
                    token_limit // 3,
                ),
            )

            memory_token_limit = max(
                1000,
                token_limit - timeline_budget,
            )

        else:
            memory_token_limit = token_limit

        context = await asyncio.to_thread(
            self._select_messages,
            rows,
            system_prompt,
            memory_token_limit,
            model_name,
        )

        if timeline_context:
            context.insert(
                1,
                {
                    "role": "system",
                    "content": (
                        "از تایم‌لاین زیر برای درک "
                        "ترتیب زمانی، هویت افراد و "
                        "رابطه Replyها استفاده کن.\n\n"
                        + timeline_context
                    ),
                },
            )

        return context

    async def trim(
        self,
        group_id: int,
    ) -> None:
        try:
            await self.store.trim_group(
                group_id,
                self.KEEP_MESSAGES,
            )

        except Exception as exc:
            print(
                f"⚠️ خطا در پاک‌سازی حافظه قدیمی: {exc}"
            )

    def get_default_token_limit(
        self,
    ) -> int:
        return self.settings.DEFAULT_TOKEN_LIMIT

    @staticmethod
    def format_user_message(
        name: str,
        user_id: int,
        text: str,
    ) -> str:
        return (
            f"[کاربر: {name} | شناسه: {user_id}]\n"
            f"{text}"
        )