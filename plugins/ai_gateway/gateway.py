from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from litellm import acompletion

from .store import AIModelStore


class AIGatewayError(Exception):
    pass


class AIGateway:
    MAX_RETRIES = 3
    RETRY_DELAYS = (1, 2, 4)

    def __init__(self, models: AIModelStore) -> None:
        self.models = models

    @staticmethod
    def _litellm_model(model: dict[str, Any]) -> str:
        provider = model["provider"].strip().rstrip("/")
        model_id = model["model_id"].strip().lstrip("/")

        if not provider or not model_id:
            raise AIGatewayError(
                "اطلاعات Provider یا Model ID ناقص است."
            )

        return f"{provider}/{model_id}"

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """
        خطاهایی که معمولاً موقتی هستند و ارزش retry دارند.
        """

        error_name = exc.__class__.__name__.lower()

        retryable_names = (
            "timeout",
            "ratelimit",
            "rate_limit",
            "connection",
            "serviceunavailable",
            "internalserver",
        )

        if any(name in error_name for name in retryable_names):
            return True

        status_code = getattr(exc, "status_code", None)

        return status_code in {
            429,
            500,
            502,
            503,
            504,
        }

    @staticmethod
    def _safe_error(exc: Exception, api_key: Optional[str]) -> str:
        error = str(exc)

        if api_key:
            error = error.replace(api_key, "***")

        return error

    async def _completion(
        self,
        kwargs: dict[str, Any],
        api_key: Optional[str],
    ):
        last_error: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                return await acompletion(**kwargs)

            except Exception as exc:
                last_error = exc

                if not self._is_retryable_error(exc):
                    raise AIGatewayError(
                        self._safe_error(exc, api_key)
                    ) from exc

                if attempt >= self.MAX_RETRIES:
                    break

                delay = self.RETRY_DELAYS[
                    min(attempt, len(self.RETRY_DELAYS) - 1)
                ]

                print(
                    f"⚠️ خطای موقت AI Gateway "
                    f"(تلاش {attempt + 1}/{self.MAX_RETRIES + 1}) - "
                    f"Retry بعد از {delay}s: "
                    f"{self._safe_error(exc, api_key)}"
                )

                await asyncio.sleep(delay)

        raise AIGatewayError(
            "سرویس AI بعد از چند تلاش متوالی پاسخ نداد. "
            "لطفاً کمی بعد دوباره امتحان کنید."
        ) from last_error

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[dict[str, Any]] = None,
        timeout: float = 60.0,
        temperature: Optional[float] = None,
    ) -> str:

        model = model or await self.models.get_active()

        if model is None:
            raise AIGatewayError(
                "هیچ مدل فعالی تنظیم نشده است."
            )

        api_key = model.get("api_key")

        kwargs: dict[str, Any] = {
            "model": self._litellm_model(model),
            "messages": messages,
            "timeout": timeout,
        }

        if api_key:
            kwargs["api_key"] = api_key

        if model.get("base_url"):
            kwargs["api_base"] = model["base_url"]

        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await self._completion(
            kwargs,
            api_key,
        )

        try:
            content = response.choices[0].message.content
        except Exception as exc:
            raise AIGatewayError(
                "پاسخ مدل ساختار قابل استفاده‌ای نداشت."
            ) from exc

        if not content:
            raise AIGatewayError(
                "مدل پاسخ متنی خالی برگرداند."
            )

        return str(content).strip()

    async def ping(
        self,
        model: dict[str, Any],
        timeout: float = 20.0,
    ) -> tuple[bool, float, str]:

        started = time.perf_counter()

        try:
            await self.chat(
                [
                    {
                        "role": "user",
                        "content": "Reply with exactly: pong",
                    }
                ],
                model=model,
                timeout=timeout,
                temperature=0,
            )

        except AIGatewayError as exc:
            latency = (
                time.perf_counter() - started
            ) * 1000

            return False, latency, str(exc)

        latency = (
            time.perf_counter() - started
        ) * 1000

        return True, latency, ""