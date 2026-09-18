from __future__ import annotations

import asyncio

from litellm import token_counter


class AIMemoryManager:
    MAX_FETCH_MESSAGES = 1000
    KEEP_MESSAGES = 1000  # بیشتر از این تعداد پیام در هر گروه نگه داشته نمی‌شه
    MESSAGE_OVERHEAD_TOKENS = 4

    def __init__(self, store, settings_store):
        self.store = store
        self.settings = settings_store

    def _select_messages(
        self,
        rows: list[dict],
        system_prompt: str,
        token_limit: int,
        model_name: str | None,
    ) -> list[dict[str, str]]:
        """
        هر پیام فقط یک بار شمرده می‌شه (O(n)). این تابع sync هست و
        داخل thread اجرا می‌شه تا event loop رو بلاک نکنه.
        """
        counter_ok = model_name is not None

        def count(text: str) -> int:
            nonlocal counter_ok

            if counter_ok:
                try:
                    return (
                        int(token_counter(model=model_name, text=text))
                        + self.MESSAGE_OVERHEAD_TOKENS
                    )
                except Exception as exc:
                    print(f"⚠️ خطا در محاسبه توکن حافظه: {exc}")
                    counter_ok = False

            # fallback تقریبی
            return max(1, len(text) // 4) + self.MESSAGE_OVERHEAD_TOKENS

        total = count(system_prompt)
        selected: list[dict[str, str]] = []

        # از جدیدترین پیام به سمت قدیمی‌تر؛ جدیدترین پیام همیشه می‌مونه.
        for row in reversed(rows):
            cost = count(row["content"])

            if selected and total + cost > token_limit:
                break

            selected.append(
                {"role": row["role"], "content": row["content"]}
            )
            total += cost

        selected.reverse()

        # اگه با پاسخ assistant شروع شده، حذفش می‌کنیم.
        if selected and selected[0]["role"] == "assistant":
            selected.pop(0)

        return [
            {"role": "system", "content": system_prompt},
            *selected,
        ]

    async def build_context(
        self,
        group_id: int,
        system_prompt: str,
        gateway,
    ) -> list[dict[str, str]]:

        token_limit = await self.settings.get_token_limit(group_id)

        rows = await self.store.get_recent(
            group_id,
            self.MAX_FETCH_MESSAGES,
        )

        model_name = None

        try:
            model = await gateway.models.get_active()

            if model is not None:
                model_name = gateway._litellm_model(model)

        except Exception as exc:
            print(f"⚠️ خطا در گرفتن مدل فعال برای شمارش توکن: {exc}")

        return await asyncio.to_thread(
            self._select_messages,
            rows,
            system_prompt,
            token_limit,
            model_name,
        )

    async def trim(self, group_id: int) -> None:
        """پیام‌های خیلی قدیمی رو پاک می‌کنه تا دیتابیس بی‌نهایت بزرگ نشه."""
        try:
            await self.store.trim_group(group_id, self.KEEP_MESSAGES)
        except Exception as exc:
            print(f"⚠️ خطا در پاک‌سازی حافظه قدیمی: {exc}")

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