
from __future__ import annotations

import io
from pathlib import Path

import aiohttp

from core.decorators import command
from core.soroush_media import send_media
from plugins.fun.cat_cache import CatCache


CAT_API_URL = "https://cataas.com/cat"
CAT_API_TIMEOUT = 10
FALLBACK_IMAGE = Path(__file__).parent / "fallback_cat.jpg"

cat_cache = CatCache()


def _detect_extension(content_type: str, data: bytes) -> str | None:
    content_type = content_type.lower().split(";", 1)[0].strip()

    if content_type == "image/jpeg" or data.startswith(b"\xff\xd8\xff"):
        return ".jpg"

    if content_type == "image/png" or data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"

    if content_type == "image/gif" or data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"

    if content_type == "image/webp" or (
        data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    ):
        return ".webp"

    return None


async def _download_cat() -> tuple[bytes, str] | None:
    timeout = aiohttp.ClientTimeout(total=CAT_API_TIMEOUT)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CAT_API_URL) as response:
                if response.status != 200:
                    return None

                data = await response.read()

                if not data:
                    return None

                extension = _detect_extension(
                    response.headers.get("Content-Type", ""),
                    data,
                )

                if extension is None:
                    return None

                return data, f"cat{extension}"

    except (aiohttp.ClientError, TimeoutError):
        return None


def _file_from_bytes(data: bytes, filename: str) -> io.BytesIO:
    file = io.BytesIO(data)
    file.name = filename
    return file


async def _send_bytes(
    client,
    chat_id,
    data: bytes,
    filename: str,
    reply_to: int,
) -> None:
    await send_media(
        client,
        chat_id,
        _file_from_bytes(data, filename),
        caption="🐈",
        reply_to=reply_to,
    )


def _load_fallback() -> tuple[bytes, str]:
    data = FALLBACK_IMAGE.read_bytes()
    return data, FALLBACK_IMAGE.name


@command(
    name="گربه",
    permission="everyone",
    chat_type="all",
    description="یک عکس تصادفی از گربه می‌فرستد.",
    native_name="cat",
)
async def cat(self, event):
    # ---------------------------------------------------------
    # 1. تلاش برای دریافت عکس جدید از API
    # ---------------------------------------------------------
    downloaded = await _download_cat()

    if downloaded is not None:
        data, filename = downloaded

        # تصویر سالم را وارد cache کن.
        cat_cache.add(data, filename)

        try:
            await _send_bytes(
                self.client,
                event.chat_id,
                data,
                filename,
                event.id,
            )
            return

        except Exception as exc:
            print(
                "[Fun] Fresh cat send failed: "
                f"{type(exc).__name__}: {exc}"
            )

    # ---------------------------------------------------------
    # 2. استفاده از عکس‌های cache شده
    # ---------------------------------------------------------
    cache_attempts = cat_cache.count

    for _ in range(cache_attempts):
        cached = cat_cache.get_random()

        if cached is None:
            break

        try:
            await _send_bytes(
                self.client,
                event.chat_id,
                cached.data,
                cached.filename,
                event.id,
            )
            return

        except Exception as exc:
            print(
                "[Fun] Cached cat send failed: "
                f"{type(exc).__name__}: {exc}"
            )

            # اگر این عکس مشخصاً قابل ارسال نیست،
            # از cache حذفش می‌کنیم تا دوباره سراغش نرویم.
            cat_cache.remove(cached.key)

    # ---------------------------------------------------------
    # 3. آخرین fallback: تصویر ثابت داخل plugin
    # ---------------------------------------------------------
    try:
        fallback_data, fallback_filename = _load_fallback()

        await _send_bytes(
            self.client,
            event.chat_id,
            fallback_data,
            fallback_filename,
            event.id,
        )
        return

    except Exception as exc:
        print(
            "[Fun] Fallback cat send failed: "
            f"{type(exc).__name__}: {exc}"
        )

    # ---------------------------------------------------------
    # 4. فقط در صورتی که تمام راه‌ها شکست خورده باشند
    # ---------------------------------------------------------
    await event.reply(
        "متأسفانه خطایی رخ داد!",
        reply_to=event.id,
    )
