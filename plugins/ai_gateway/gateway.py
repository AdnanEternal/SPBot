from __future__ import annotations

import asyncio
import aiohttp
import time

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from typing import Any, Optional
from dataclasses import dataclass

from litellm import acompletion
from .store import (
    AIModelStore,
    AIModelStatisticsStore,
)


class AIGatewayError(Exception):
    pass


class AIGatewayContextLengthError(AIGatewayError):
    """
    ورودی از سقف context مدل رد شده. برخلاف AIGatewayError عادی،
    یه بار با context بسیار کوچیک‌شده دوباره تلاش می‌شه
    قبل از اینکه واقعاً شکست بخوریم.
    """
    pass


class AIGatewayRetryExhaustedError(
    AIGatewayError
):
    """
    همه تلاش‌های retry شکست خورده‌اند،
    ولی اطلاعات خطای واقعی آخرین تلاش حفظ می‌شود.
    """
    pass

@dataclass(frozen=True)
class APIKeyFailureDecision:
    status: str | None
    reason: str | None
    cooldown_seconds: float | None = None

    @property
    def should_change_key(self) -> bool:
        return self.status in {
            "COOLDOWN",
            "INVALID",
        }


class APIKeyFailureError(AIGatewayError):
    def __init__(
        self,
        decision: APIKeyFailureDecision,
        original_error: Exception,
    ) -> None:
        self.decision = decision
        self.original_error = original_error

        super().__init__(
            str(original_error)
        )

class AIGateway:
    DEBUG_LOGGING = False


    MAX_RETRIES = 3
    RETRY_DELAYS = (1, 2, 4)
    PING_CONCURRENCY = 15

    AI_CONCURRENCY = 3

    KEY_REASON_AUTHENTICATION = (
        "AUTHENTICATION"
    )

    KEY_REASON_INVALID_KEY = (
        "INVALID_KEY"
    )

    KEY_REASON_RATE_LIMIT = (
        "RATE_LIMIT"
    )

    KEY_REASON_DAILY_QUOTA = (
        "DAILY_QUOTA"
    )

    KEY_REASON_UNKNOWN = (
        "UNKNOWN"
    )

    # -------------------------------------------------
    # عباراتی که با اطمینان نسبتاً بالا نشان می‌دهند
    # خود API Key نامعتبر / منقضی / revoke شده است.
    # -------------------------------------------------

    EXPLICIT_INVALID_KEY_PHRASES = (
        "invalid api key",
        "invalid api token",
        "api key is invalid",
        "api key invalid",
        "incorrect api key",
        "incorrect api token",
        "expired api key",
        "expired api token",
        "revoked api key",
        "revoked api token",
        "api key revoked",
        "api token revoked",
        "authentication failed",
        "invalid credentials",
        "invalid authentication",
        "authentication credentials are invalid",
        "api key does not exist",
        "api key not found",
    )

    # -------------------------------------------------
    # عبارت‌های مشخص مربوط به quota / مصرف / billing
    # -------------------------------------------------

    DAILY_QUOTA_PHRASES = (
        "quota exhausted",
        "quota exceeded",
        "quota has been exceeded",
        "current quota",
        "exceeded your current quota",
        "daily quota",
        "daily limit",
        "daily usage limit",
        "daily usage",
        "daily requests limit",
        "daily request limit",
        "daily tokens limit",
        "daily token limit",
        "monthly quota",
        "monthly limit",
        "monthly usage limit",
        "free tier limit",
        "free tier quota",
        "usage limit exceeded",
        "usage limit reached",
        "usage quota exceeded",
        "usage quota reached",
        "credits exhausted",
        "credits exceeded",
        "credit limit exceeded",
        "credit limit reached",
        "spending limit exceeded",
        "spend limit exceeded",
        "budget exceeded",
        "budget limit exceeded",
        "billing hard limit",
        "hard limit exceeded",
        "insufficient_quota",
    )

    # -------------------------------------------------
    # عبارت‌هایی که معمولاً نشان‌دهنده Rate Limit
    # کوتاه‌مدت هستند.
    # -------------------------------------------------

    RATE_LIMIT_PHRASES = (
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        "requests per minute",
        "request per minute",
        "requests per second",
        "request per second",
        "tokens per minute",
        "token per minute",
        "tokens per second",
        "token per second",
        "rpm limit",
        "tpm limit",
    )

    # -------------------------------------------------
    # Rate Limitهایی که مربوط به خود deployment /
    # concurrency هستند، نه API Key.
    # -------------------------------------------------

    NON_KEY_RATE_LIMIT_PHRASES = (
        "max_parallel_requests",
        "maximum parallel requests",
        "max parallel requests",
        "deployment has all",
        "too many requests for deployment",
        "all slots are busy",
        "all slots in use",
        "concurrency limit",
        "concurrent request limit",
        "max concurrent requests",
    )

    def __init__(
        self,
        models: AIModelStore,
        statistics: AIModelStatisticsStore,
    ) -> None:
        
        self.models = models
        self.statistics = statistics

        self._ai_semaphore = asyncio.Semaphore(
            self.AI_CONCURRENCY
        )


    def debug(
        self,
        category: str,
        message: str,
    ) -> None:
        if not self.DEBUG_LOGGING:
            return

        print(
            f"[AIGateway][{category}] {message}",
            flush=True,
        )


    @staticmethod
    def _classify_error(
        exc: Exception,
    ) -> str:

        error_name = (
            exc.__class__.__name__.lower()
        )

        status_code = getattr(
            exc,
            "status_code",
            None,
        )

        message = str(
            exc
        ).lower()

        provider_fields = str(
            getattr(
                exc,
                "provider_specific_fields",
                "",
            )
        ).lower()

        combined = (
            message
            + " "
            + provider_fields
        )

        if AIGateway._is_context_length_error(
            exc
        ):
            return "CONTEXT"

        if status_code in {
            401,
            403,
        }:
            return "AUTHENTICATION"

        quota_keywords = (
            "quota",
            "insufficient_quota",
            "daily limit",
            "usage limit",
            "credits exhausted",
        )

        if any(
            keyword in combined
            for keyword in quota_keywords
        ):
            return "QUOTA"

        if (
            status_code == 429
            or "ratelimit" in error_name
            or "rate_limit" in error_name
            or "rate limit" in message
        ):
            return "RATE_LIMIT"

        if (
            status_code in {
                408,
                504,
            }
            or "timeout" in error_name
        ):
            return "TIMEOUT"

        if status_code in {
            500,
            502,
            503,
        }:
            return "SERVER_ERROR"

        return "UNKNOWN"


    @staticmethod
    def _extract_retry_after_seconds(
        exc: Exception,
    ) -> float | None:

        # ---------------------------------------------
        # مستقیم روی Exception
        # ---------------------------------------------

        value = getattr(
            exc,
            "retry_after",
            None,
        )

        if value is not None:
            try:
                seconds = float(value)

                if seconds >= 0:
                    return seconds

            except (
                TypeError,
                ValueError,
            ):
                pass

        # ---------------------------------------------
        # provider_specific_fields
        # ---------------------------------------------

        provider_fields = getattr(
            exc,
            "provider_specific_fields",
            None,
        )

        if isinstance(
            provider_fields,
            dict,
        ):
            value = provider_fields.get(
                "retry_after"
            )

            if value is not None:
                try:
                    seconds = float(value)

                    if seconds >= 0:
                        return seconds

                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        # ---------------------------------------------
        # HTTP response headers
        # فقط Retry-After را می‌خوانیم.
        # چون معنای آن نسبتاً مشخص است.
        # ---------------------------------------------

        response = getattr(
            exc,
            "response",
            None,
        )

        headers = getattr(
            response,
            "headers",
            None,
        )

        if headers:
            retry_after = None

            try:
                retry_after = headers.get(
                    "retry-after"
                )

                if retry_after is None:
                    retry_after = headers.get(
                        "Retry-After"
                    )

            except Exception:
                retry_after = None

            if retry_after is not None:
                try:
                    seconds = float(
                        retry_after
                    )

                    if seconds >= 0:
                        return seconds

                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        return None


    @classmethod
    def classify_api_key_failure(
        cls,
        exc: Exception,
    ) -> APIKeyFailureDecision:

        status_code = getattr(
            exc,
            "status_code",
            None,
        )

        error_name = (
            exc.__class__.__name__.lower()
        )

        error_text = (
            cls._build_error_text(
                exc
            )
        )

        # -------------------------------------------------
        # 0. Context Length
        #
        # مشکل ورودی است، نه API Key.
        # -------------------------------------------------

        if cls._is_context_length_error(
            exc
        ):
            return APIKeyFailureDecision(
                status=None,
                reason=None,
            )

        # -------------------------------------------------
        # 1. Explicit invalid / revoked / expired key
        #
        # متن صریح از status code مهم‌تر است.
        # -------------------------------------------------

        if any(
            phrase in error_text
            for phrase
            in cls.EXPLICIT_INVALID_KEY_PHRASES
        ):
            return APIKeyFailureDecision(
                status="INVALID",
                reason=(
                    cls.KEY_REASON_INVALID_KEY
                ),
            )

        # -------------------------------------------------
        # 2. HTTP 401 / AuthenticationError
        #
        # در این مرحله فرض می‌کنیم authentication
        # واقعاً برای credential فعلی شکست خورده.
        # -------------------------------------------------

        if (
            status_code in {
                401,
                403
            }
            or "authenticationerror" in error_name
            or "authentication error" in error_name
        ):
            return APIKeyFailureDecision(
                status="INVALID",
                reason=(
                    cls.KEY_REASON_AUTHENTICATION
                ),
            )

        # -------------------------------------------------
        # 3. Daily / account quota
        #
        # این شرط باید قبل از generic 429 باشد،
        # چون بسیاری از quota errorها با 429 می‌آیند.
        # -------------------------------------------------

        if any(
            phrase in error_text
            for phrase
            in cls.DAILY_QUOTA_PHRASES
        ):
            return APIKeyFailureDecision(
                status="COOLDOWN",
                reason=(
                    cls.KEY_REASON_DAILY_QUOTA
                ),
                cooldown_seconds=(
                    cls._extract_retry_after_seconds(
                        exc
                    )
                ),
            )

        # -------------------------------------------------
        # 4. Rate Limit
        # -------------------------------------------------

        is_rate_limit = (
            status_code == 429
            or "ratelimiterror" in error_name
            or any(
                phrase in error_text
                for phrase
                in cls.RATE_LIMIT_PHRASES
            )
        )

        if is_rate_limit:

            # ---------------------------------------------
            # بعضی 429ها اصلاً مربوط به Key نیستند.
            # ---------------------------------------------

            if any(
                phrase in error_text
                for phrase
                in cls.NON_KEY_RATE_LIMIT_PHRASES
            ):
                return APIKeyFailureDecision(
                    status=None,
                    reason=None,
                )

            return APIKeyFailureDecision(
                status="COOLDOWN",
                reason=(
                    cls.KEY_REASON_RATE_LIMIT
                ),
                cooldown_seconds=(
                    cls._extract_retry_after_seconds(
                        exc
                    )
                ),
            )

        # -------------------------------------------------
        # 5. بقیه خطاها
        #
        # فعلاً Key را متهم نمی‌کنیم.
        # -------------------------------------------------

        return APIKeyFailureDecision(
            status=None,
            reason=None,
        )
    
    @staticmethod
    def _build_error_text(
        exc: Exception,
    ) -> str:

        message = str(
            exc
        ).lower()

        provider_fields = getattr(
            exc,
            "provider_specific_fields",
            None,
        )

        provider_text = (
            str(
                provider_fields
            ).lower()
            if provider_fields
            else ""
        )

        error_name = (
            exc.__class__.__name__.lower()
        )

        return " ".join(
            (
                error_name,
                message,
                provider_text,
            )
        )


    @staticmethod
    def _error_details(
        exc: Exception,
    ) -> str:

        parts = []

        error_type = (
            exc.__class__.__name__
        )

        parts.append(
            f"type={error_type}"
        )

        status_code = getattr(
            exc,
            "status_code",
            None,
        )

        if status_code is not None:
            parts.append(
                f"status={status_code}"
            )

        llm_provider = getattr(
            exc,
            "llm_provider",
            None,
        )

        if llm_provider:
            parts.append(
                f"provider={llm_provider}"
            )

        retry_after = getattr(
            exc,
            "retry_after",
            None,
        )

        if retry_after is not None:
            parts.append(
                f"retry_after={retry_after}"
            )

        provider_specific_fields = getattr(
            exc,
            "provider_specific_fields",
            None,
        )

        if provider_specific_fields:
            parts.append(
                "provider_fields="
                + str(
                    provider_specific_fields
                )
            )

        message = str(exc).strip()

        if message:
            parts.append(
                f"message={message}"
            )

        return " | ".join(parts)


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
        statistics_name: str | None = None,
    ) -> tuple[bool, float, str]:

        started = time.perf_counter()

        model = {
            "name": (
                statistics_name
                or model_id
            ),
            "provider": api_key_data[
                "provider"
            ],
            "model_id": model_id,
            "api_key": api_key_data[
                "api_key"
            ],
            "base_url": api_key_data.get(
                "base_url"
            ),
        }

        try:
            await self.chat(
                [
                    {
                        "role": "user",
                        "content": (
                            "Reply with exactly: pong"
                        ),
                    }
                ],
                model=model,
                timeout=timeout,
                record_statistics=False,
            )

        except AIGatewayError as exc:

            latency = (
                time.perf_counter()
                - started
            ) * 1000

            if statistics_name:
                try:
                    await self.statistics.record_ping_failure(
                        statistics_name,
                        latency,
                        str(exc),
                    )

                except Exception as stats_exc:
                    print(
                        "⚠️ ثبت Ping ناموفق بود: "
                        f"{stats_exc}"
                    )

            return False, latency, str(exc)

        except Exception as exc:

            latency = (
                time.perf_counter()
                - started
            ) * 1000

            if statistics_name:
                try:
                    await self.statistics.record_ping_failure(
                        statistics_name,
                        latency,
                        str(exc),
                    )

                except Exception as stats_exc:
                    self.debug(
                        "STATS",
                        (
                            "event=PING_FAILURE_RECORD_FAILED "
                            f"error_type={type(stats_exc).__name__}"
                        ),
                    )

            return False, latency, str(exc)

        latency = (
            time.perf_counter()
            - started
        ) * 1000

        if statistics_name:
            try:
                await self.statistics.record_ping_success(
                    statistics_name,
                    latency,
                )

            except Exception as stats_exc:
                self.debug(
                    "STATS",
                    (
                        "event=FAILURE_RECORD_FAILED "
                        f"error_type={type(stats_exc).__name__}"
                    ),
                )

        return True, latency, ""




    async def ping_remote_models(
        self,
        api_key_data: dict,
        models: list[str],
        timeout: float = 20.0,
    ) -> list[tuple[str, bool, float, str]]:

        configured_models = (
            await self.models.get_all()
        )

        normalized_provider = (
            self._normalize_provider(
                api_key_data["provider"]
            )
            .strip()
            .lower()
        )

        base_url = (
            api_key_data.get("base_url")
            or ""
        ).strip().rstrip("/")

        # ---------------------------------------------
        # Map remote model_id -> internal model name
        # فقط مدل‌هایی که واقعاً داخل ai_models هستند.
        # ---------------------------------------------

        statistics_names: dict[
            str,
            str,
        ] = {}

        for configured in configured_models:

            configured_provider = (
                self._normalize_provider(
                    configured["provider"]
                )
                .strip()
                .lower()
            )

            configured_base_url = (
                configured.get("base_url")
                or ""
            ).strip().rstrip("/")

            if (
                configured["model_id"].strip()
                != ""
                and configured["model_id"].strip()
                in models
                and configured_provider
                == normalized_provider
                and configured_base_url
                == base_url
            ):
                statistics_names[
                    configured["model_id"].strip()
                ] = configured["name"]

        semaphore = asyncio.Semaphore(
            self.PING_CONCURRENCY
        )

        async def worker(
            model_id: str,
        ) -> tuple[str, bool, float, str]:

            async with semaphore:

                try:

                    statistics_name = (
                        statistics_names.get(
                            model_id
                        )
                    )

                    ok, latency, error = (
                        await self.ping_remote_model(
                            api_key_data,
                            model_id,
                            timeout,
                            statistics_name,
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







    async def _get_model_candidates(
        self,
    ) -> list[dict[str, Any]]:

        models = await self.models.get_all()

        if not models:
            return []

        active_model = await self.models.get_active()

        statistics = (
            await self.statistics.get_all()
        )

        statistics_map = {
            stats["model_name"]: stats
            for stats in statistics
        }

        active_name = (
            active_model["name"]
            if active_model is not None
            else None
        )

        fallback_models = [
            model
            for model in models
            if (
                active_name is None
                or model["name"] != active_name
            )
        ]

        def overall_score(
            model: dict[str, Any],
        ) -> int:

            stats = statistics_map.get(
                model["name"]
            )

            if stats is None:
                return 50

            return self.statistics.calculate_overall_score(
                stats
            )

        fallback_models.sort(
            key=overall_score,
            reverse=True,
        )

        if active_model is not None:
            return [
                active_model,
                *fallback_models,
            ]

        return fallback_models



    async def _apply_api_key_failure(
        self,
        model_name: str | None,
        api_key_number: int | None,
        exc: Exception,
    ) -> APIKeyFailureDecision:

        decision = (
            self.classify_api_key_failure(
                exc
            )
        )

        # ---------------------------------------------
        # این request الزاماً به یک Key ذخیره‌شده
        # متعلق نیست.
        #
        # مثلاً ping_remote_model ممکن است یک model
        # موقت با api_key مستقیم بسازد.
        # ---------------------------------------------

        if (
            model_name is None
            or api_key_number is None
            or not decision.should_change_key
        ):
            return decision

        cooldown_until = None

        if decision.status == "COOLDOWN":

            # ---------------------------------------------
            # Provider زمان cooldown را صریحاً داده.
            # ---------------------------------------------

            if decision.cooldown_seconds is not None:

                cooldown_until = (
                    datetime.now(
                        timezone.utc
                    )
                    + timedelta(
                        seconds=decision.cooldown_seconds
                    )
                ).isoformat()

            # ---------------------------------------------
            # Provider زمان جدیدی نداده.
            #
            # اگر این Key از قبل COOLDOWN بوده،
            # cooldown قبلی را خراب نکن.
            # ---------------------------------------------

            else:

                try:

                    current_keys = (
                        await self.models.get_api_keys(
                            model_name
                        )
                    )

                    current_key = next(
                        (
                            key
                            for key in current_keys
                            if int(
                                key["key_number"]
                            ) == int(
                                api_key_number
                            )
                        ),
                        None,
                    )

                    if (
                        current_key is not None
                        and current_key.get("status")
                        == self.models.KEY_STATUS_COOLDOWN
                    ):
                        cooldown_until = (
                            current_key.get(
                                "cooldown_until"
                            )
                        )

                except Exception as lookup_exc:

                    self.debug(
                        "KEY_STATUS",
                        (
                            f"model={model_name} "
                            f"key=#{api_key_number} "
                            "event=READ_PREVIOUS_STATUS_FAILED "
                            f"error_type={type(lookup_exc).__name__}"
                        ),
                    )

        try:

            await self.models.set_api_key_status(
                model_name,
                api_key_number,
                decision.status,
                cooldown_until=cooldown_until,
                reason=decision.reason,
            )

        except Exception as db_exc:

            self.debug(
                "KEY_STATUS",
                (
                    f"model={model_name} "
                    f"key=#{api_key_number} "
                    "event=UPDATE_FAILED "
                    f"error_type={type(db_exc).__name__}"
                ),
            )

        else:

            self.debug(
                "KEY_STATUS",
                (
                    f"model={model_name} "
                    f"key=#{api_key_number} "
                    f"event=UPDATED "
                    f"status={decision.status} "
                    f"reason={decision.reason or '-'} "
                    f"cooldown_until={cooldown_until or '-'}"
                ),
            )

        return decision

    async def _completion(
        self,
        kwargs: dict[str, Any],
        api_key: Optional[str],
        *,
        statistics_name: str | None = None,
        api_key_number: int | None = None,
        record_statistics: bool = True,
    ):
        last_error: Optional[Exception] = None

        total_attempts = (
            self.MAX_RETRIES + 1
        )

        for attempt in range(
            total_attempts
        ):
            try:
                return await acompletion(
                    **kwargs
                )

            except Exception as exc:
                last_error = exc

                safe_error = (
                    self._safe_error(
                        exc,
                        api_key,
                    )
                )

                error_class = (
                    self._classify_error(
                        exc
                    )
                )

                if (
                    record_statistics
                    and statistics_name
                ):
                    try:
                        await self.statistics.record_attempt_error(
                            statistics_name,
                            error_class,
                            safe_error,
                        )

                    except Exception as stats_exc:
                        self.debug(
                            "STATS",
                            (
                                "event=ATTEMPT_ERROR_RECORD_FAILED "
                                f"error_type={type(stats_exc).__name__}"
                            ),
                        )

                detailed_error = (
                    self._error_details(
                        exc
                    )
                )

                self.debug(
                    "REQUEST",
                    (
                        f"event=FAILED "
                        f"attempt={attempt + 1}/{total_attempts} "
                        f"class={error_class} "
                        f"model={kwargs.get('model')} "
                        f"error={self._safe_error(detailed_error, api_key)}"
                    ),
                )

                # =================================================
                # 1. اول بررسی می‌کنیم آیا مشکل از API Key است.
                #
                # اگر بله:
                # - هیچ retry انجام نمی‌شود.
                # - وضعیت Key فوراً ذخیره می‌شود.
                # - یک Exception اختصاصی بالا می‌رود تا chat بتواند
                #   بعداً Key بعدی را انتخاب کند.
                # =================================================

                key_decision = (
                    self.classify_api_key_failure(
                        exc
                    )
                )

                self.debug(
                    "CLASSIFY",
                    (
                        f"model={kwargs.get('model')} "
                        f"key=#{api_key_number or '?'} "
                        f"status={key_decision.status or '-'} "
                        f"reason={key_decision.reason or '-'} "
                        f"cooldown_seconds="
                        f"{key_decision.cooldown_seconds}"
                    ),
                )

                if key_decision.should_change_key:

                    await self._apply_api_key_failure(
                        statistics_name,
                        api_key_number,
                        exc,
                    )

                    self.debug(
                        "KEY",
                        (
                            f"model={statistics_name} "
                            f"key=#{api_key_number or '?'} "
                            "event=FAILURE "
                            f"status={key_decision.status} "
                            f"reason={key_decision.reason or '-'} "
                            "retry=NO"
                        ),
                    )

                    raise APIKeyFailureError(
                        key_decision,
                        exc,
                    ) from exc

                # =================================================
                # 2. Context Length
                #
                # مشکل Key نیست و منطق مخصوص خودش را دارد.
                # =================================================

                if self._is_context_length_error(
                    exc
                ):
                    raise AIGatewayContextLengthError(
                        safe_error
                    ) from exc

                # =================================================
                # 3. خطاهای موقتی:
                # فقط اینجا اجازه retry داریم.
                # =================================================

                if not self._is_retryable_error(
                    exc
                ):
                    raise AIGatewayError(
                        f"[{error_class}] "
                        f"{detailed_error}"
                    ) from exc

                # =================================================
                # 4. هنوز retry باقی مانده؟
                # =================================================

                if attempt >= self.MAX_RETRIES:
                    break

                delay = self.RETRY_DELAYS[
                    min(
                        attempt,
                        len(
                            self.RETRY_DELAYS
                        ) - 1,
                    )
                ]

                self.debug(
                    "RETRY",
                    (
                        f"model={kwargs.get('model')} "
                        f"attempt={attempt + 1}/{total_attempts} "
                        f"class={error_class} "
                        f"delay={delay}s"
                    ),
                )

                await asyncio.sleep(
                    delay
                )

        if last_error is None:
            raise AIGatewayRetryExhaustedError(
                "هیچ خطای مشخصی ثبت نشد."
            )

        # =================================================
        # تمام retryهای خطای غیر-Key تمام شده‌اند.
        # =================================================

        await self._apply_api_key_failure(
            statistics_name,
            api_key_number,
            last_error,
        )

        error_class = (
            self._classify_error(
                last_error
            )
        )

        detailed_error = (
            self._error_details(
                last_error
            )
        )

        raise AIGatewayRetryExhaustedError(
            f"[{error_class}] "
            f"پس از {total_attempts} تلاش ناموفق. "
            f"آخرین خطا: {detailed_error}"
        ) from last_error


    @staticmethod
    def _safe_error(exc: Exception, api_key: Optional[str]) -> str:
        error = str(exc)

        if api_key:
            error = error.replace(api_key, "***")

        return error

        
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[dict[str, Any]] = None,
        timeout: float = 60.0,
        temperature: Optional[float] = None,
        return_metadata: bool = False,
        record_statistics: bool = True,
    ) -> str | tuple[str, dict[str, Any]]:

        # -------------------------------------------------
        # Candidate models
        # -------------------------------------------------
        if model is not None:

            # وقتی مدل به‌صورت صریح مشخص شده،
            # فقط همان مدل استفاده شود.
            candidates = [
                model
            ]

        else:

            # مدل Active اولین انتخاب است.
            # بعد از آن، مدل‌ها بر اساس Overall Score
            # از بیشترین به کمترین مرتب می‌شوند.
            candidates = (
                await self._get_model_candidates()
            )

        if not candidates:
            raise AIGatewayError(
                "هیچ مدلی برای ارسال درخواست وجود ندارد."
            )

        last_error: Optional[Exception] = None

        # -------------------------------------------------
        # Fallback loop
        # -------------------------------------------------

        async with self._ai_semaphore:

            for index, candidate in enumerate(candidates):

                litellm_model = self._litellm_model(
                    candidate
                )

                # ---------------------------------------------
                # تمام API Keyهای قابل استفاده این Model
                # Active Key در صورت سالم بودن، اولین Key است.
                # ---------------------------------------------

                if model is not None:

                    # وقتی مدل به‌صورت صریح از بیرون داده شده،
                    # هنوز rotation دیتابیسی انجام نمی‌دهیم.
                    #
                    # این مسیر برای ping و استفاده مستقیم
                    # از model dict حفظ می‌شود.

                    candidate_keys = [
                        {
                            "api_key": candidate.get(
                                "api_key"
                            ),
                            "key_number": candidate.get(
                                "api_key_number"
                            ),
                        }
                    ]

                else:

                    candidate_keys = (
                        await self.models.get_api_key_candidates(
                            candidate["name"]
                        )
                    )

                    self.debug(
                        "KEY_POOL",
                        (
                            f"model={litellm_model} "
                            f"keys="
                            + ",".join(
                                (
                                    f"#{key.get('key_number')}:"
                                    f"{key.get('status') or 'UNKNOWN'}"
                                    f"{'*' if key.get('is_active') else ''}"
                                )
                                for key in candidate_keys
                            )
                            if candidate_keys
                            else "keys=EMPTY"
                        ),
                    )

                if not candidate_keys:

                    self.debug(
                        "KEY",
                        (
                            f"model={litellm_model} "
                            "event=NO_CANDIDATE_KEY"
                        ),
                    )

                    continue

                # ---------------------------------------------
                # Key Rotation
                # ---------------------------------------------


                for key_index, key_data in enumerate(
                    candidate_keys
                ):

                    api_key = (
                        key_data.get(
                            "api_key"
                        )
                    )

                    api_key_number = (
                        key_data.get(
                            "key_number"
                        )
                    )

                    is_probe = (
                        key_data.get("status")
                        == self.models.KEY_STATUS_COOLDOWN
                    )

                    self.debug(
                        "KEY",
                        (
                            f"model={litellm_model} "
                            f"key=#{api_key_number or '?'} "
                            f"status={key_data.get('status') or 'UNKNOWN'} "
                            f"probe={'YES' if is_probe else 'NO'} "
                            f"position={key_index + 1}/{len(candidate_keys)}"
                        ),
                    )

                    kwargs: dict[str, Any] = {
                        "model": litellm_model,
                        "messages": messages,
                        "timeout": timeout,
                    }

                    if api_key:
                        kwargs["api_key"] = api_key

                    if candidate.get("base_url"):
                        kwargs["api_base"] = (
                            candidate["base_url"]
                        )

                    if temperature is not None:
                        kwargs["temperature"] = temperature

                    model_started = (
                        time.perf_counter()
                    )

                    try:

                        self.debug(
                            "REQUEST",
                            (
                                f"event=KEY_ATTEMPT "
                                f"model={litellm_model} "
                                f"key=#{api_key_number or '?'} "
                                f"position={key_index + 1}/{len(candidate_keys)}"
                            ),
                        )

                        response = (
                            await self._completion(
                                kwargs,
                                api_key,
                                statistics_name=(
                                    candidate["name"]
                                ),
                                api_key_number=(
                                    api_key_number
                                ),
                                record_statistics=(
                                    record_statistics
                                ),
                            )
                        )

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

                        model_latency_ms = (
                            time.perf_counter()
                            - model_started
                        ) * 1000

                        # ---------------------------------------------
                        # اگر این Key به‌صورت Probe از COOLDOWN آمده
                        # و درخواست موفق شده، دوباره AVAILABLE شود.
                        # ---------------------------------------------

                        if (
                            key_data.get("status")
                            == self.models.KEY_STATUS_COOLDOWN
                        ):

                            try:
                                self.debug(
                                    "PROBE",
                                    (
                                        f"model={litellm_model} "
                                        f"key=#{api_key_number or '?'} "
                                        "event=SUCCESS "
                                        "status=AVAILABLE"
                                    ),
                                )

                                restored = (
                                    await self.models.mark_api_key_available(
                                        candidate["name"],
                                        api_key_number,
                                        reason="PROBE_SUCCESS",
                                    )
                                )

                                if restored:

                                    print(
                                        "✅ API KEY PROBE SUCCESS | "
                                        f"model={litellm_model} | "
                                        f"key=#{api_key_number}"
                                    )

                            except Exception as status_exc:

                                self.debug(
                                    "PROBE",
                                    (
                                        f"model={litellm_model} "
                                        f"key=#{api_key_number} "
                                        "event=RESTORE_STATUS_FAILED "
                                        f"error_type={type(status_exc).__name__}"
                                    ),
                                )

                        if record_statistics:
                            try:
                                await self.statistics.record_success(
                                    candidate["name"],
                                    model_latency_ms,
                                )

                            except Exception as stats_exc:
                                print(
                                    "⚠️ ثبت موفقیت مدل ناموفق بود: "
                                    f"{stats_exc}"
                                )

                        self.debug(
                            "SUCCESS",
                            (
                                f"model={litellm_model} "
                                f"key=#{api_key_number or '?'} "
                                f"latency={model_latency_ms:.0f}ms"
                            ),
                        )

                        if not return_metadata:
                            return content

                        return (
                            content,
                            {
                                "model": litellm_model,
                                "provider": candidate.get(
                                    "provider"
                                ),
                                "model_id": candidate.get(
                                    "model_id"
                                ),
                                "base_url": candidate.get(
                                    "base_url"
                                ),
                                "api_key_number": (
                                    api_key_number
                                ),
                                "usage": self._extract_usage(
                                    response
                                ),
                            },
                        )

                    except APIKeyFailureError as exc:


                        model_latency_ms = (
                            time.perf_counter()
                            - model_started
                        ) * 1000

                        last_error = exc

                        self.debug(
                            "KEY",
                            (
                                f"model={litellm_model} "
                                f"key=#{api_key_number or '?'} "
                                "event=UNAVAILABLE "
                                f"status={exc.decision.status} "
                                f"reason={exc.decision.reason or '-'} "
                                "retry=NO"
                            ),
                        )

                        # -------------------------------------
                        # مشکل از همین Key بود.
                        #
                        # هیچ retry روی همین Key نداریم.
                        # مستقیم Key بعدی همین Model.
                        # -------------------------------------

                        if (
                            key_index
                            + 1
                            < len(candidate_keys)
                        ):

                            self.debug(
                                "ROTATION",
                                (
                                    f"model={litellm_model} "
                                    f"from_key=#{api_key_number or '?'} "
                                    f"to_key=#"
                                    f"{candidate_keys[key_index + 1].get('key_number')}"
                                ),
                            )

                            continue

                        # هیچ Key سالم دیگری در این Model
                        # باقی نمانده.
                        self.debug(
                            "ROTATION",
                            (
                                f"model={litellm_model} "
                                "event=ALL_KEYS_EXHAUSTED"
                            ),
                        )

                        break

                    except Exception as exc:

                        model_latency_ms = (
                            time.perf_counter()
                            - model_started
                        ) * 1000

                        last_error = exc

                        error_category = (
                            self._classify_error(
                                exc
                            )
                        )

                        safe_error = (
                            self._safe_error(
                                str(exc),
                                api_key,
                            )
                        )

                        if record_statistics:
                            try:
                                await self.statistics.record_failure(
                                    candidate["name"]
                                )

                            except Exception as stats_exc:
                                print(
                                    "⚠️ ثبت آمار شکست مدل ناموفق بود: "
                                    f"{stats_exc}"
                                )

                        self.debug(
                            "MODEL",
                            (
                                f"event=FAILED "
                                f"model={litellm_model} "
                                f"key=#{api_key_number or '?'} "
                                f"class={error_category} "
                                f"latency={model_latency_ms:.0f}ms "
                                f"error={safe_error}"
                            ),
                        )

                        # -------------------------------------
                        # این خطا Key-specific نیست.
                        #
                        # timeout / connection / 5xx و ...
                        # منطق retry خود _completion را دارند.
                        #
                        # اگر تمام retryها هم شکست خورده‌اند،
                        # Model را تمام‌شده در نظر می‌گیریم
                        # و می‌رویم سراغ Model بعدی.
                        # -------------------------------------

                        break

                # ---------------------------------------------
                # همه Keyهای این Model unavailable شدند
                # یا Model با یک خطای non-key شکست خورد.
                #
                # حالا fallback بین Modelها.
                # ---------------------------------------------

                if index + 1 < len(candidates):

                    self.debug(
                        "FALLBACK",
                        (
                            f"from_model={litellm_model} "
                            f"to_model="
                            f"{self._litellm_model(candidates[index + 1])}"
                        ),
                    )

                    continue
        # -------------------------------------------------
        # All models failed
        # -------------------------------------------------

        if last_error is not None:
            raise AIGatewayError(
                "همه مدل‌های موجود برای پاسخ‌گویی "
                "ناموفق بودند. "
                f"آخرین خطا: {last_error}"
            ) from last_error

        raise AIGatewayError(
            "درخواست AI بدون دریافت پاسخ پایان یافت."
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
                record_statistics=False,
            )

        except Exception as exc:

            latency = (
                time.perf_counter()
                - started
            ) * 1000

            try:
                await self.statistics.record_ping_failure(
                    model["name"],
                    latency,
                    str(exc),
                )

            except Exception as stats_exc:
                print(
                    "⚠️ ثبت Ping ناموفق بود: "
                    f"{stats_exc}"
                )

            return False, latency, str(exc)

        latency = (
            time.perf_counter()
            - started
        ) * 1000

        try:
            await self.statistics.record_ping_success(
                model["name"],
                latency,
            )

        except Exception as stats_exc:
            print(
                "⚠️ ثبت Ping موفق بود ولی ذخیره آمار "
                f"ناموفق شد: {stats_exc}"
            )

        return True, latency, ""