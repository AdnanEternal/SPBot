
from __future__ import annotations

import io
import mimetypes
import re

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from core.soroush_media import send_media

from splusthon.tl import types

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


def find_trigger_words(
    text: str | None,
    trigger_words,
) -> tuple[str, ...]:
    """
    فقط تریگرهای موجود در متن را تشخیص می‌دهد.

    - محدودیت تعداد کلمات ندارد.
    - امکان کشیدگی حروف را حفظ می‌کند.
    - نتیجه را بر اساس ترتیب ظهور تریگرها برمی‌گرداند.
    - هر تریگر را حداکثر یک بار برمی‌گرداند.

    تصمیم درباره معتبر بودن پیام با قابلیت مربوطه است.
    """

    text = (text or "").strip()

    if not text:
        return ()

    matches = []

    for raw_word in trigger_words:
        word = str(raw_word).strip()

        if not word:
            continue

        match = _compile_stretched_word(word).search(text)

        if match is None:
            continue

        matches.append(
            (
                match.start(),
                match.end(),
                word,
            )
        )

    matches.sort(
        key=lambda item: (
            item[0],
            -(item[1] - item[0]),
        )
    )

    result = []
    seen = set()

    for _, _, word in matches:
        normalized = word.casefold()

        if normalized in seen:
            continue

        seen.add(normalized)
        result.append(word)

    return tuple(result)


def count_words(
    text: str | None,
) -> int:
    """تعداد کلمات متن را حساب می‌کند."""

    return len(
        _WORD_PATTERN.findall(text or "")
    )


def matches_trigger_words(
    text: str | None,
    trigger_words,
    *,
    max_words: int | None = 5,
) -> bool:
    """
    ابزار سازگار با استفاده‌های قبلی.

    این تابع علاوه بر تشخیص، محدودیت طول را نیز اعمال می‌کند.
    برای سیاست‌های جدید ترجیحاً از find_trigger_words استفاده شود.
    """

    text = (text or "").strip()

    if not text:
        return False

    if (
        max_words is not None
        and count_words(text) > max_words
    ):
        return False

    return bool(
        find_trigger_words(
            text,
            trigger_words,
        )
    )


def is_media_response(
    content_type: str,
    data: bytes,
) -> bool:
    """
    اعتبارسنجی پاسخ رسانه‌ای تصویر یا ویدئو.

    GIF نیز به عنوان image پشتیبانی می‌شود.
    تشخیص امضای فایل کمک می‌کند اگر Content-Type دقیق نبود،
    فایل معتبر را بی‌دلیل رد نکنیم.
    """

    content_type = (
        content_type or ""
    ).split(";", 1)[0].strip().lower()

    if content_type.startswith(
        ("image/", "video/")
    ):
        return True

    if is_image_response(
        content_type,
        data,
    ):
        return True

    # MP4 / فایل‌های مبتنی بر ISO Base Media
    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):
        return True

    # WebM / EBML
    if data.startswith(
        b"\x1a\x45\xdf\xa3"
    ):
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

    # اگر نوع محتوا عمومی بود، پسوند URL را بررسی کن.
    if extension and extension != ".bin":
        return extension

    if url:
        url_extension = Path(
            urlparse(url).path
        ).suffix.lower()

        if url_extension and len(url_extension) <= 10:
            return url_extension

    if extension:
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
    """ارسال تصویر، GIF یا ویدئو با متادیتای مناسب."""

    if not data:
        raise ValueError(
            "Cannot send an empty file."
        )

    extension = Path(filename).suffix.lower()
    media_options = dict(kwargs)

    if extension == ".gif":
        # SPlusthon برای GIF به صفت Animated نیاز دارد.
        attributes = list(
            media_options.get("attributes") or []
        )

        if not any(
            isinstance(
                attribute,
                types.DocumentAttributeAnimated,
            )
            for attribute in attributes
        ):
            attributes.append(
                types.DocumentAttributeAnimated()
            )

        media_options["attributes"] = attributes
        media_options.setdefault(
            "mime_type",
            "image/gif",
        )

    elif extension == ".mp4":
        media_options.setdefault(
            "mime_type",
            "video/mp4",
        )
        media_options.setdefault(
            "supports_streaming",
            True,
        )
        media_options.setdefault(
            "nosound_video",
            True,
        )

    elif extension == ".webm":
        media_options.setdefault(
            "mime_type",
            "video/webm",
        )
        media_options.setdefault(
            "nosound_video",
            True,
        )

    file = io.BytesIO(data)
    file.name = filename

    return await send_media(
        plugin.client,
        event.chat_id,
        file,
        caption=caption,
        reply_to=event.id,
        **media_options,
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