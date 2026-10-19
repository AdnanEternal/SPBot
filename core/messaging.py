
"""
ابزارهای مشترک ارسال پیام با پشتیبانی از متادیتای نامرئی.
"""

from __future__ import annotations

import json
from typing import Any


# چهار نویسهٔ نامرئی برای کدگذاری اطلاعات
_INVISIBLE_ALPHABET = (
    "\u200b",  # Zero Width Space
    "\u200c",  # Zero Width Non-Joiner
    "\u200d",  # Zero Width Joiner
    "\u2060",  # Word Joiner
)

# جداکنندهٔ ابتدا و انتهای متادیتا
_METADATA_DELIMITER = "\u2063"


def _encode_metadata(meta_data: Any) -> str:
    """
    متادیتا را به رشته‌ای از نویسه‌های نامرئی تبدیل می‌کند.

    این تابع فعلاً فقط کدگذاری می‌کند؛
    استخراج و رمزگشایی متادیتا در مرحلهٔ بعد اضافه می‌شود.
    """

    if isinstance(meta_data, str):
        raw = meta_data.encode("utf-8")
    else:
        raw = json.dumps(
            meta_data,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    invisible_chars = []

    for byte in raw:
        # هر بایت به چهار بخش دو بیتی تبدیل می‌شود.
        for shift in (6, 4, 2, 0):
            value = (byte >> shift) & 0b11
            invisible_chars.append(
                _INVISIBLE_ALPHABET[value]
            )

    return (
        _METADATA_DELIMITER
        + "".join(invisible_chars)
        + _METADATA_DELIMITER
    )


def _prepare_message(
    message: str,
    meta_data: Any = None,
) -> str:
    """متن پیام را برای ارسال آماده می‌کند."""

    if not isinstance(message, str):
        raise TypeError(
            "message باید از نوع str باشد."
        )

    if meta_data is None:
        return message

    return _encode_metadata(meta_data) + message


async def safe_reply(
    event,
    message: str,
    meta_data: Any = None,
    **kwargs,
):
    """ارسال پاسخ به پیام فعلی، با متادیتای اختیاری."""

    prepared_message = _prepare_message(
        message,
        meta_data,
    )

    return await event.reply(
        prepared_message,
        **kwargs,
    )


async def safe_send_message(
    client,
    chat_id,
    message: str,
    meta_data: Any = None,
    **kwargs,
):
    """ارسال پیام به یک گفتگو، با متادیتای اختیاری."""

    prepared_message = _prepare_message(
        message,
        meta_data,
    )

    return await client.send_message(
        chat_id,
        prepared_message,
        **kwargs,
    )


def extract_metadata(message: str) -> str | bool:
    """
    متادیتای نامرئی ابتدای پیام را استخراج می‌کند.

    اگر متادیتا وجود نداشته باشد یا ساختارش نامعتبر باشد،
    False برمی‌گرداند.
    """

    if not isinstance(message, str):
        return False

    if not message.startswith(_METADATA_DELIMITER):
        return False

    start = len(_METADATA_DELIMITER)

    end = message.find(
        _METADATA_DELIMITER,
        start,
    )

    if end == -1:
        return False

    encoded = message[start:end]

    if not encoded or len(encoded) % 4 != 0:
        return False

    char_to_value = {
        char: index
        for index, char in enumerate(
            _INVISIBLE_ALPHABET
        )
    }

    decoded_bytes = bytearray()

    for offset in range(0, len(encoded), 4):
        chunk = encoded[offset:offset + 4]

        try:
            values = [
                char_to_value[char]
                for char in chunk
            ]
        except KeyError:
            return False

        byte_value = (
            (values[0] << 6)
            | (values[1] << 4)
            | (values[2] << 2)
            | values[3]
        )

        decoded_bytes.append(byte_value)

    try:
        return decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return False