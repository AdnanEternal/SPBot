from __future__ import annotations

import asyncio
import aiohttp

import time
from typing import Any, Optional

from litellm import acompletion

from .store import AIModelStore


class AIGatewayError(Exception):
    pass


class AIGatewayContextLengthError(AIGatewayError):
    """
    ورودی از سقف context مدل رد شده. برخلاف AIGatewayError عادی،
    یه بار با context بسیار کوچیک‌شده دوباره تلاش می‌شه
    قبل از اینکه واقعاً شکست بخوریم.
    """
    pass


class AIGateway:
    MAX_RETRIES = 3
    RETRY_DELAYS = (1, 2, 4)
    PING_CONCURRENCY = 15

    AI_CONCURRENCY = 3

    def __init__(
        self,
        models: AIModelStore,
    ) -> None:
        self.models = models

        self._ai_semaphore = asyncio.Semaphore(
            self.AI_CONCURRENCY
        )

    @staticmethod
    def _extract_usage(
        response,
    ) -> dict[str, Any]:

        usage = getattr(
            response,
            "usage",
            None,
        )

        if usage is None:
            return {}

        if isinstance(
            usage,
            dict,
        ):
            return {
                "prompt_tokens": usage.get(
                    "prompt_tokens"
                ),
                "completion_tokens": usage.get(
                    "completion_tokens"
                ),
                "total_tokens": usage.get(
                    "total_tokens"
                ),
            }

        return {
            "prompt_tokens": getattr(
                usage,
                "prompt_tokens",
                None,
            ),
            "completion_tokens": getattr(
                usage,
                "completion_tokens",
                None,
            ),
            "total_tokens": getattr(
                usage,
                "total_tokens",
                None,
            ),
        }

    
    @staticmethod
    def _normalize_provider(provider: str) -> str:
        provider = provider.strip().lower()

        if provider in {
            "zai",
            "z.ai",
            "z-ai",
        }:
            return "openai"

        return provider

    @staticmethod
    def _models_url(api_key_data: dict) -> str:
        explicit_url = api_key_data.get("models_url")

        if explicit_url:
            return explicit_url.rstrip("/")

        base_url = api_key_data.get("base_url")

        if not base_url:
            raise AIGatewayError(
                "Base URL برای گرفتن لیست مدل‌ها تنظیم نشده است."
            )

        return base_url.rstrip("/") + "/models"

    async def list_remote_models(
        self,
        api_key_data: dict,
        timeout: float = 15.0,
    ) -> list[str]:

        url = self._models_url(api_key_data)

        headers = {
            "Authorization": f"Bearer {api_key_data['api_key']}",
        }

        timeout_config = aiohttp.ClientTimeout(
            total=timeout
        )

        try:
            async with aiohttp.ClientSession(
                timeout=timeout_config
            ) as session:

                async with session.get(
                    url,
                    headers=headers,
                ) as response:

                    text = await response.text()

                    if response.status != 200:
                        raise AIGatewayError(
                            f"HTTP {response.status}: {text[:300]}"
                        )

                    try:
                        data = await response.json(
                            content_type=None
                        )
                    except Exception as exc:
                        raise AIGatewayError(
                            "پاسخ API برای /models قابل خواندن نبود."
                        ) from exc

        except asyncio.TimeoutError as exc:
            raise AIGatewayError(
                "درخواست دریافت مدل‌ها Timeout شد."
            ) from exc

        except aiohttp.ClientError as exc:
            raise AIGatewayError(
                f"خطای اتصال: {exc}"
            ) from exc

        models = data.get("data")

        if not isinstance(models, list):
            raise AIGatewayError(
                "پاسخ API شامل لیست data نیست."
            )

        result = []

        for item in models:
            if not isinstance(item, dict):
                continue

            model_id = item.get("id")

            if model_id:
                result.append(str(model_id))

        return sorted(set(result))


    async def ping_remote_model(
        self,
        api_key_data: dict,
        model_id: str,
        timeout: float = 20.0,
    ) -> tuple[bool, float, str]:

        started = time.perf_counter()

        model = {
            "name": model_id,
            "provider": api_key_data["provider"],
            "model_id": model_id,
            "api_key": api_key_data["api_key"],
            "base_url": api_key_data.get("base_url"),
        }

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
            )

        except AIGatewayError as exc:
            latency = (
                time.perf_counter() - started
            ) * 1000

            return False, latency, str(exc)

        except Exception as exc:
            latency = (
                time.perf_counter() - started
            ) * 1000

            return False, latency, str(exc)

        latency = (
            time.perf_counter() - started
        ) * 1000

        return True, latency, ""


    async def ping_remote_models(
        self,
        api_key_data: dict,
        models: list[str],
        timeout: float = 20.0,
) -> list[tuple[str, bool, float, str]]:

        semaphore = asyncio.Semaphore(
            self.PING_CONCURRENCY
        )

        async def worker(
            model_id: str,
        ) -> tuple[str, bool, float, str]:

            async with semaphore:
                try:
                    ok, latency, error = (
                        await self.ping_remote_model(
                            api_key_data,
                            model_id,
                            timeout,
                        )
                    )

                    return (
                        model_id,
                        ok,
                        latency,
                        error,
                    )

                except Exception as exc:
                    return (
                        model_id,
                        False,
                        0,
                        str(exc),
                    )

        results = await asyncio.gather(
            *(
                worker(model_id)
                for model_id in models
            )
        )

        return results

    

    @staticmethod
    def _litellm_model(model: dict[str, Any]) -> str:
        provider = AIGateway._normalize_provider(
            model["provider"]
        ).strip().rstrip("/")
        model_id = model["model_id"].strip().lstrip("/")

        if not provider or not model_id:
            raise AIGatewayError(
                "اطلاعات Provider یا Model ID ناقص است."
            )

        return f"{provider}/{model_id}"


    @staticmethod
    def _is_context_length_error(exc: Exception) -> bool:
        error_name = exc.__class__.__name__.lower()

        if (
            "contextwindow" in error_name
            or "context_length" in error_name
            or "contextlength" in error_name
        ):
            return True

        message = str(exc).lower()

        return (
            "context length" in message
            or "context_length_exceeded" in message
            or "maximum context" in message
            or "too many tokens" in message
            or "reduce the length" in message
        )


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

                if self._is_context_length_error(exc):
                    raise AIGatewayContextLengthError(
                        self._safe_error(exc, api_key)
                    ) from exc

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
        return_metadata: bool = False,
    ) -> str | tuple[str, dict[str, Any]]:

        model = (
            model
            or await self.models.get_active()
        )

        if model is None:
            raise AIGatewayError(
                "هیچ مدل فعالی تنظیم نشده است."
            )

        api_key = model.get("api_key")

        # -------------------------------------------------
        # LiteLLM model identifier
        # -------------------------------------------------

        litellm_model = (
            self._litellm_model(
                model
            )
        )

        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
            "timeout": timeout,
        }

        if api_key:
            kwargs["api_key"] = api_key

        if model.get("base_url"):
            kwargs["api_base"] = (
                model["base_url"]
            )

        if temperature is not None:
            kwargs["temperature"] = (
                temperature
            )

        # -------------------------------------------------
        # Request
        # -------------------------------------------------

        async with self._ai_semaphore:
            try:
                response = await self._completion(
                    kwargs,
                    api_key,
                )
            except AIGatewayContextLengthError:
                shrunk_message = []

                if messages:
                    shrunk_message.append(messages[0])

                for message in reversed(messages):
                    if message.get("role") == "user":
                        shrunk_message.append(message)
                        break

                if (
                    not shrunk_message
                    or len(shrunk_message) >= len(message)
                ):
                    raise AIGatewayError(
                        "پیام حتی بعد از کوچیک‌کردن context"
                        "هم بیش از حد مجاز مدل بود."
                    )

                print(
                    "⚠️ Context از سقف مدل رد شد؛ "
                    "تلاش دوباره با context بسیار کوچیک‌شده..."
                )

                kwargs["messages"] = shrunk_message

                response = await self._completion(
                    kwargs,
                    api_key
                )
        # -------------------------------------------------
        # Extract content
        # -------------------------------------------------

        try:
            content = (
                response
                .choices[0]
                .message
                .content
            )

        except Exception as exc:
            raise AIGatewayError(
                "پاسخ مدل ساختار قابل استفاده‌ای نداشت."
            ) from exc

        if not content:
            raise AIGatewayError(
                "مدل پاسخ متنی خالی برگرداند."
            )

        content = str(
            content
        ).strip()

        # -------------------------------------------------
        # Normal mode
        # -------------------------------------------------

        if not return_metadata:
            return content

        # -------------------------------------------------
        # Telemetry metadata
        # -------------------------------------------------

        return (
            content,
            {
                "model": litellm_model,
                "provider": model.get(
                    "provider"
                ),
                "model_id": model.get(
                    "model_id"
                ),
                "base_url": model.get(
                    "base_url"
                ),
                "usage": self._extract_usage(
                    response
                ),
            },
        )
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