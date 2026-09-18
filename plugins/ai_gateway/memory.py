from __future__ import annotations

from litellm import token_counter


class AIMemoryManager:
    MAX_FETCH_MESSAGES = 1000

    def __init__(self, store, settings_store):
        self.store = store
        self.settings = settings_store

    async def _count_tokens(
        self,
        messages: list[dict[str, str]],
        gateway,
    ) -> int:
        try:
            model = await gateway.models.get_active()

            if model is not None:
                model_name = gateway._litellm_model(model)

                return int(
                    token_counter(
                        model=model_name,
                        messages=messages,
                    )
                )

        except Exception as exc:
            print(f"⚠️ خطا در محاسبه توکن حافظه: {exc}")

        # fallback تقریبی
        return sum(
            max(1, len(message["content"]) // 4) + 4
            for message in messages
        )

    async def build_context(
        self,
        group_id: int,
        system_prompt: str,
        gateway,
    ) -> list[dict[str, str]]:

        token_limit = await self.settings.get_token_limit(
            group_id
        )

        recent = await self.store.get_recent(
            group_id,
            self.MAX_FETCH_MESSAGES,
        )

        selected: list[dict[str, str]] = []

        # از جدیدترین پیام به سمت قدیمی‌تر حرکت می‌کنیم.
        for row in reversed(recent):
            candidate = [
                {"role": "system", "content": system_prompt}
            ]

            candidate.extend(reversed(selected))

            candidate.append(
                {
                    "role": row["role"],
                    "content": row["content"],
                }
            )

            token_count = await self._count_tokens(
                candidate,
                gateway,
            )

            if token_count <= token_limit or not selected:
                selected.append(
                    {
                        "role": row["role"],
                        "content": row["content"],
                    }
                )
            else:
                break

        selected.reverse()

        # اگر انتخاب حافظه با پاسخ assistant شروع شده،
        # آن پاسخ را حذف می‌کنیم تا context منطقی‌تر باشد.
        if selected and selected[0]["role"] == "assistant":
            selected.pop(0)

        return [
            {
                "role": "system",
                "content": system_prompt,
            },
            *selected,
        ]

    def get_default_token_limit(self) -> int:
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