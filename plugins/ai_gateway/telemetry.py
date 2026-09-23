from __future__ import annotations

import asyncio
from typing import Any

from core.time_manager import format_project_time
from litellm import token_counter


class AITelemetryManager:
    """
    Live Telemetry مخصوص AI Gateway.

    نکته مهم:
    این کلاس نباید مسیر اصلی AI را متوقف کند.

    emit_*:
        فقط اطلاعات را داخل Queue می‌گذارد.
        هیچ await / network / database ندارد.

    Worker:
        در پس‌زمینه پیام Telemetry را به گروه مقصد ارسال می‌کند.
    """

    QUEUE_MAX_SIZE = 100

    def __init__(
        self,
        client,
    ) -> None:
        self.client = client

        self._target_group_id: int | None = None

        self._queue: (
            asyncio.Queue[dict[str, Any]]
            | None
        ) = None

        self._worker_task: (
            asyncio.Task
            | None
        ) = None

    # =====================================================
    # STATE
    # =====================================================

    @property
    def enabled(self) -> bool:
        return (
            self._target_group_id
            is not None
        )

    @property
    def target_group_id(self) -> int | None:
        return self._target_group_id

    def set_target(
        self,
        group_id: int,
    ) -> None:
        self._target_group_id = int(
            group_id
        )

    def clear_target(self) -> None:
        self._target_group_id = None

    # =====================================================
    # WORKER
    # =====================================================

    async def start(self) -> None:
        if (
            self._worker_task is not None
            and not self._worker_task.done()
        ):
            return

        self._queue = asyncio.Queue(
            maxsize=self.QUEUE_MAX_SIZE
        )

        self._worker_task = (
            asyncio.create_task(
                self._worker()
            )
        )

    async def shutdown(self) -> None:
        task = self._worker_task

        self._worker_task = None
        self._queue = None

        if task is None:
            return

        task.cancel()

        try:
            await task

        except asyncio.CancelledError:
            pass

    # =====================================================
    # PUBLIC EMITTERS
    # =====================================================

    def emit_success(
        self,
        *,
        event,
        sender,
        group_id: int,
        trigger: str,
        context: list[dict[str, str]],
        answer: str,
        latency_ms: float,
        total_duration_ms: float,
        model_info: dict[str, Any],
    ) -> None:

        target = (
            self._target_group_id
        )

        queue = self._queue

        if (
            target is None
            or queue is None
        ):
            return

        payload = {
            "target_group_id": target,
            "kind": "success",
            "event_date": getattr(
                event,
                "date",
                None,
            ),
            "sender": (
                self._build_sender_info(
                    sender,
                    event,
                )
            ),
            "group_id": group_id,
            "trigger": trigger,
            "context": context,
            "answer": answer,
            "latency_ms": latency_ms,
            "total_duration_ms": (
                total_duration_ms
            ),
            "model_info": model_info,
        }

        self._enqueue(
            payload
        )

    def emit_failure(
        self,
        *,
        event,
        sender,
        group_id: int,
        trigger: str,
        context: list[dict[str, str]] | None,
        error: Exception,
        request_latency_ms: float | None,
        total_duration_ms: float | None,
        stage: str,
    ) -> None:

        target = (
            self._target_group_id
        )

        queue = self._queue

        if (
            target is None
            or queue is None
        ):
            return

        payload = {
            "target_group_id": target,
            "kind": "failure",
            "event_date": getattr(
                event,
                "date",
                None,
            ),
            "sender": (
                self._build_sender_info(
                    sender,
                    event,
                )
            ),
            "group_id": group_id,
            "trigger": trigger,
            "context": context or [],
            "error_type": (
                error.__class__.__name__
            ),
            "error": str(error),
            "request_latency_ms": (
                request_latency_ms
            ),
            "total_duration_ms": (
                total_duration_ms
            ),
            "stage": stage,
        }

        self._enqueue(
            payload
        )

    # =====================================================
    # QUEUE
    # =====================================================

    def _enqueue(
        self,
        payload: dict[str, Any],
    ) -> None:

        queue = self._queue

        if queue is None:
            return

        try:
            queue.put_nowait(
                payload
            )

        except asyncio.QueueFull:
            # هرگز مسیر AI را متوقف نکن.
            # اگر Telemetry عقب افتاد، Telemetry drop می‌شود.
            pass

    # =====================================================
    # USER INFO
    # =====================================================

    @staticmethod
    def _build_sender_info(
        sender,
        event,
    ) -> dict[str, Any]:

        username = (
            getattr(
                sender,
                "username",
                None,
            )
            if sender is not None
            else None
        )

        first_name = (
            getattr(
                sender,
                "first_name",
                None,
            )
            if sender is not None
            else None
        )

        last_name = (
            getattr(
                sender,
                "last_name",
                None,
            )
            if sender is not None
            else None
        )

        display_name = " ".join(
            value
            for value in (
                first_name,
                last_name,
            )
            if value
        ).strip()

        if not display_name:
            display_name = (
                username
                or str(
                    getattr(
                        event,
                        "sender_id",
                        None,
                    )
                )
            )

        return {
            "user_id": getattr(
                event,
                "sender_id",
                None,
            ),
            "username": username,
            "display_name": display_name,
        }

    # =====================================================
    # BACKGROUND WORKER
    # =====================================================

    async def _worker(self) -> None:

        while True:

            queue = self._queue

            if queue is None:
                return

            payload = await queue.get()

            try:
                message = (
                    await self._format_message(
                        payload
                    )
                )

                await self.client.send_message(
                    payload[
                        "target_group_id"
                    ],
                    message,
                )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                print(
                    "⚠️ خطا در ارسال "
                    "AI Telemetry: "
                    f"{exc}"
                )

            finally:
                queue.task_done()

    # =====================================================
    # FORMAT
    # =====================================================

    async def _format_message(
        self,
        payload: dict[str, Any],
    ) -> str:

        context = (
            payload.get(
                "context"
            )
            or []
        )

        # این محاسبه داخل Worker انجام می‌شود،
        # نه مسیر اصلی AI.
        input_chars = sum(
            len(
                str(
                    message.get(
                        "content",
                        "",
                    )
                )
            )
            for message in context
        )

        sender = (
            payload.get(
                "sender"
            )
            or {}
        )

        username = (
            sender.get(
                "username"
            )
        )

        display_name = (
            sender.get(
                "display_name"
            )
            or "نامشخص"
        )

        user_label = display_name

        if username:
            user_label += (
                f" (@{username})"
            )

        event_date = payload.get(
            "event_date"
        )

        event_time = (
            format_project_time(
                event_date
            )
            if event_date is not None
            else "نامشخص"
        )

        if payload["kind"] == "success":
            return await self._format_success(
                payload=payload,
                context=context,
                input_chars=input_chars,
                event_time=event_time,
                user_label=user_label,
            )

        return self._format_failure(
            payload=payload,
            event_time=event_time,
            user_label=user_label,
        )

    async def _format_success(
        self,
        *,
        payload: dict[str, Any],
        context: list[dict[str, str]],
        input_chars: int,
        event_time: str,
        user_label: str,
    ) -> str:

        sender = payload["sender"]

        model_info = (
            payload.get(
                "model_info"
            )
            or {}
        )

        model_name = (
            model_info.get(
                "model"
            )
            or "نامشخص"
        )

        usage = (
            model_info.get(
                "usage"
            )
            or {}
        )

        prompt_tokens = (
            usage.get(
                "prompt_tokens"
            )
        )

        completion_tokens = (
            usage.get(
                "completion_tokens"
            )
        )

        total_tokens = (
            usage.get(
                "total_tokens"
            )
        )

        token_source = "API"

        # اگر Provider usage نداد،
        # Telemetry در پس‌زمینه خودش محاسبه می‌کند.
        if (
            prompt_tokens is None
            or completion_tokens is None
            or total_tokens is None
        ):

            fallback = (
                await self._calculate_fallback_tokens(
                    model_name,
                    context,
                    payload["answer"],
                )
            )

            if prompt_tokens is None:
                prompt_tokens = (
                    fallback[
                        "prompt_tokens"
                    ]
                )

            if completion_tokens is None:
                completion_tokens = (
                    fallback[
                        "completion_tokens"
                    ]
                )

            if total_tokens is None:
                total_tokens = (
                    fallback[
                        "total_tokens"
                    ]
                )

            token_source = (
                "محاسبه محلی"
            )

        return (
            "📡 AI TELEMETRY\n\n"
            "✅ درخواست موفق بود\n\n"

            f"👤 کاربر: {user_label}\n"
            f"🆔 User ID: "
            f"{sender['user_id']}\n"

            f"🏠 Group ID: "
            f"{payload['group_id']}\n"

            f"🕒 زمان: "
            f"{event_time}\n\n"

            f"⚡ Trigger: "
            f"{payload['trigger']}\n"

            f"🤖 Model: "
            f"{model_name}\n\n"

            "📥 ورودی مدل\n"
            f"• Context messages: "
            f"{len(context)}\n"

            f"• Characters: "
            f"{input_chars:,}\n"

            f"• Input tokens: "
            f"{self._format_number(prompt_tokens)}\n\n"

            "📤 خروجی مدل\n"
            f"• Characters: "
            f"{len(payload['answer']):,}\n"

            f"• Output tokens: "
            f"{self._format_number(completion_tokens)}\n\n"

            "⏱️ عملکرد\n"
            f"• Model latency: "
            f"{payload['latency_ms']:.0f}ms\n"

            f"• Total processing: "
            f"{payload['total_duration_ms']:.0f}ms\n"

            f"• Total tokens: "
            f"{self._format_number(total_tokens)}\n"

            f"• Token source: "
            f"{token_source}"
        )

    @staticmethod
    def _format_failure(
        *,
        payload: dict[str, Any],
        event_time: str,
        user_label: str,
    ) -> str:

        sender = payload["sender"]

        error = str(
            payload.get(
                "error",
                "",
            )
        ).strip()

        if len(error) > 900:
            error = (
                error[:897]
                + "..."
            )

        request_latency = (
            payload.get(
                "request_latency_ms"
            )
        )

        total_duration = (
            payload.get(
                "total_duration_ms"
            )
        )

        request_text = (
            f"{request_latency:.0f}ms"
            if request_latency is not None
            else "شروع نشده"
        )

        total_text = (
            f"{total_duration:.0f}ms"
            if total_duration is not None
            else "نامشخص"
        )

        return (
            "📡 AI TELEMETRY\n\n"
            "❌ درخواست ناموفق بود\n\n"

            f"👤 کاربر: "
            f"{user_label}\n"

            f"🆔 User ID: "
            f"{sender['user_id']}\n"

            f"🏠 Group ID: "
            f"{payload['group_id']}\n"

            f"🕒 زمان: "
            f"{event_time}\n\n"

            f"⚡ Trigger: "
            f"{payload['trigger']}\n\n"

            "❌ خطا\n"

            f"• مرحله: "
            f"{payload['stage']}\n"

            f"• نوع: "
            f"{payload['error_type']}\n"

            f"• دلیل: "
            f"{error or 'نامشخص'}\n\n"

            "⏱️ عملکرد\n"

            f"• Request: "
            f"{request_text}\n"

            f"• Total processing: "
            f"{total_text}"
        )

    # =====================================================
    # TOKEN FALLBACK
    # =====================================================

    @staticmethod
    async def _calculate_fallback_tokens(
        model_name: str,
        context: list[dict[str, str]],
        answer: str,
    ) -> dict[str, int | None]:

        try:

            input_text = "\n".join(
                str(
                    message.get(
                        "content",
                        "",
                    )
                )
                for message in context
            )

            prompt_tokens = int(
                await asyncio.to_thread(
                    token_counter,
                    model=model_name,
                    text=input_text,
                )
            )

            completion_tokens = int(
                await asyncio.to_thread(
                    token_counter,
                    model=model_name,
                    text=answer,
                )
            )

            return {
                "prompt_tokens": (
                    prompt_tokens
                ),
                "completion_tokens": (
                    completion_tokens
                ),
                "total_tokens": (
                    prompt_tokens
                    + completion_tokens
                ),
            }

        except Exception:
            return {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            }

    @staticmethod
    def _format_number(
        value: Any,
    ) -> str:

        if value is None:
            return "نامشخص"

        try:
            return f"{int(value):,}"

        except Exception:
            return str(value)