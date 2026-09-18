from __future__ import annotations

from typing import Any, Optional

from litellm import acompletion

from .store import AIModelStore


class AIGatewayError(Exception):
    pass


class AIGateway:
    def __init__(self, models: AIModelStore) -> None:
        self.models = models

    @staticmethod
    def _litellm_model(model: dict[str, Any]) -> str:
        provider = model["provider"].strip().rstrip("/")
        model_id = model["model_id"].strip().lstrip("/")
        if not provider or not model_id:
            raise AIGatewayError("اطلاعات provider یا model ID ناقص است.")
        return f"{provider}/{model_id}"

    async def chat(self, messages: list[dict[str, str]], *, model: Optional[dict[str, Any]] = None, timeout: float = 60.0, temperature: Optional[float] = None) -> str:
        model = model or await self.models.get_active()
        if model is None:
            raise AIGatewayError("هیچ مدل فعالی تنظیم نشده است.")
        api_key = model.get("api_key")
        kwargs: dict[str, Any] = {"model": self._litellm_model(model), "messages": messages, "timeout": timeout}
        if api_key:
            kwargs["api_key"] = api_key
        if model.get("base_url"):
            kwargs["api_base"] = model["base_url"]
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            response = await acompletion(**kwargs)
            content = response.choices[0].message.content
        except Exception as exc:
            error = str(exc)
            if api_key:
                error = error.replace(api_key, "***")
            raise AIGatewayError(error) from exc
        if not content:
            raise AIGatewayError("مدل پاسخ متنی خالی برگرداند.")
        return str(content).strip()

    async def ping(self, model: dict[str, Any], timeout: float = 20.0) -> tuple[bool, float, str]:
        import time
        started = time.perf_counter()
        try:
            await self.chat([{"role": "user", "content": "Reply with exactly: pong"}], model=model, timeout=timeout, temperature=0)
        except AIGatewayError as exc:
            return False, (time.perf_counter() - started) * 1000, str(exc)
        return True, (time.perf_counter() - started) * 1000, ""