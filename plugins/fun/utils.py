
from __future__ import annotations

import io
import mimetypes
import re

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from core.soroush_media import send_media


_WORD_PATTERN = re.compile(
    r"\w+",
    re.UNICODE,
)

FALLBACK_IMAGE = (
    Path(__file__).parent / "fallback.jpg"
)


@lru_cache(maxsize=128)
def _compile_stretched_word(
    word: str,
) -> re.Pattern[str]:
    word = word.strip()

    if not word:
        raise ValueError(
            "Trigger word cannot be empty."
        )

    body = "".join(
        re.escape(char) + "+"
        for char in word
    )

    return re.compile(
        rf"(?<!\w)(?:{body})(?!\w)",
        re.UNICODE | re.IGNORECASE,
    )


def matches_trigger_words(
    text: str | None,
    trigger_words,
    *,
    max_words: int | None = 5,
) -> bool:
    """
    ابزار عمومی تشخیص کلمه‌های مستقل با امکان
    کشیدگی حروف و محدودیت تعداد کلمات.

    سیاست نهایی هر قابلیت باید در خود همان قابلیت
    تعیین شود؛ این تابع صرفاً ابزار تطبیق است.
    """

    text = (text or "").strip()

    if not text:
        return False

    words = _WORD_PATTERN.findall(text)

    if (
        max_words is not None
        and len(words) > max_words
    ):
        return False

    for word in trigger_words:
        word = str(word).strip()

        if not word:
            continue

        if _compile_stretched_word(word).search(text):
            return True

    return False


def is_image_response(
    content_type: str,
    data: bytes,
) -> bool:
    content_type = (
        content_type or ""
    ).split(";", 1)[0].strip().lower()

    if content_type.startswith("image/"):
        return True

    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith((b"GIF87a", b"GIF89a"))
        or (
            data.startswith(b"RIFF")
            and data[8:12] == b"WEBP"
        )
    )


def guess_file_extension(
    content_type: str,
    data: bytes,
    *,
    url: str | None = None,
) -> str:
    content_type = (
        content_type or ""
    ).split(";", 1)[0].strip().lower()

    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"

    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"

    if (
        data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        return ".webp"

    known_extensions = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "text/html": ".html",
        "text/plain": ".txt",
        "application/json": ".json",
    }

    if content_type in known_extensions:
        return known_extensions[content_type]

    extension = mimetypes.guess_extension(
        content_type,
        strict=False,
    )

    if extension:
        return extension

    if url:
        extension = Path(
            urlparse(url).path
        ).suffix.lower()

        if extension and len(extension) <= 10:
            return extension

    return ".bin"


async def send_media_bytes(
    plugin,
    event,
    data: bytes,
    filename: str,
    *,
    caption: str = "",
    **kwargs,
):
    """
    ارسال فایل با ابزار رسانه‌ی مشترک SPBot.
    تفسیر پاسخ API وظیفه‌ی این تابع نیست.
    """

    if not data:
        raise ValueError(
            "Cannot send an empty file."
        )

    file = io.BytesIO(data)
    file.name = filename

    return await send_media(
        plugin.client,
        event.chat_id,
        file,
        caption=caption,
        reply_to=event.id,
        **kwargs,
    )


async def send_fallback_image(
    plugin,
    event,
    *,
    caption: str = "",
):
    """
    ارسال تصویر مشترک fallback.jpg.
    تصمیم استفاده از فال‌بک با قابلیت فراخواننده است.
    """

    data = FALLBACK_IMAGE.read_bytes()

    return await send_media_bytes(
        plugin,
        event,
        data,
        FALLBACK_IMAGE.name,
        caption=caption,
    )