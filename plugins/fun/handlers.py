from __future__ import annotations

import json

from urllib.parse import urlparse

from splusthon import events

from core.decorators import command, on_event

from .api_client import (
    APIClientError,
    request_api,
)

from .utils import (
    guess_file_extension,
    is_image_response,
    matches_trigger_words,
    send_fallback_image,
    send_media_bytes,
    should_skip_trigger_on_bot_reply,
)


# ---------------------------------------------------------
# CAT FEATURE
# ---------------------------------------------------------

CAT_API_URL = "https://cataas.com/cat"

CAT_API_TIMEOUT = 10

CAT_TRIGGER_WORDS = (
    "میو",
    "گربه",
    "پیشی",
)


def _find_url_in_payload(
    value,
) -> str | None:
    """
    منطق مخصوص قابلیت گربه:
    در پاسخ JSON، آدرس مستقیم تصویر را پیدا می‌کند.

    این منطق عمداً در api_client.py نیست؛
    هر قابلیت شکل پاسخ مورد انتظار خودش را می‌شناسد.
    """

    preferred_keys = (
        "image_url",
        "image",
        "url",
        "src",
        "link",
    )

    if isinstance(value, str):
        candidate = value.strip()

        if urlparse(candidate).scheme in (
            "http",
            "https",
        ):
            return candidate

        return None

    if isinstance(value, dict):
        for key in preferred_keys:
            if key in value:
                found = _find_url_in_payload(
                    value[key]
                )

                if found:
                    return found

        for child in value.values():
            found = _find_url_in_payload(child)

            if found:
                return found

    elif isinstance(value, list):
        for child in value:
            found = _find_url_in_payload(child)

            if found:
                return found

    return None


async def _resolve_cat_image(
    response,
) -> tuple[bytes, str] | None:
    """
    پاسخ API گربه را تفسیر می‌کند.

    پشتیبانی:
        - تصویر مستقیم
        - JSON حاوی URL تصویر
        - متن ساده‌ای که خودش URL است

    هر نوع پاسخ دیگری برای این قابلیت
    قابل استفاده نیست و به فال‌بک می‌رسد.
    """

    if not response.ok:
        return None

    # حالت اول: خود پاسخ، تصویر است.
    if is_image_response(
        response.content_type,
        response.body,
    ):
        extension = guess_file_extension(
            response.content_type,
            response.body,
            url=response.url,
        )

        return (
            response.body,
            f"cat{extension}",
        )

    image_url = None

    # حالت دوم: پاسخ JSON است.
    if response.is_json:
        try:
            payload = response.json()

        except (ValueError, json.JSONDecodeError):
            payload = None

        if payload is not None:
            image_url = _find_url_in_payload(
                payload
            )

    # حالت سوم: بدنه خودش URL است.
    elif response.content_type.startswith("text/"):
        candidate = response.text().strip()

        if (
            candidate.startswith("https://")
            or candidate.startswith("http://")
        ):
            image_url = candidate

    if not image_url:
        return None

    # URL استخراج شده باید خودش دریافت شود.
    image_response = await request_api(
        image_url,
        timeout=CAT_API_TIMEOUT,
        max_bytes=15 * 1024 * 1024,
    )

    if not image_response.ok:
        return None

    if not is_image_response(
        image_response.content_type,
        image_response.body,
    ):
        return None

    extension = guess_file_extension(
        image_response.content_type,
        image_response.body,
        url=image_response.url,
    )

    return (
        image_response.body,
        f"cat{extension}",
    )


async def _run_cat(
    self,
    event,
) -> None:
    """
    عمل مستقل قابلیت گربه.
    هم کامند و هم تریگر به همین تابع می‌رسند.
    """

    self.debug(
        "CAT",
        (
            "START "
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"message={event.id}"
        ),
    )

    try:
        response = await request_api(
            CAT_API_URL,
            timeout=CAT_API_TIMEOUT,
            max_bytes=15 * 1024 * 1024,
        )

        image = await _resolve_cat_image(
            response
        )

    except APIClientError as exc:
        image = None

        self.debug(
            "API",
            (
                f"FAILED "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

    except Exception as exc:
        image = None

        self.debug(
            "CAT",
            (
                f"UNEXPECTED_ERROR "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

    # -------------------------------------------------
    # API RESULT
    # -------------------------------------------------

    if image is not None:
        data, filename = image

        try:
            await send_media_bytes(
                self,
                event,
                data,
                filename,
            )

            self.debug(
                "CAT",
                f"SUCCESS source=api file={filename}",
            )
            return

        except Exception as exc:
            self.debug(
                "SEND",
                (
                    "API_IMAGE_FAILED "
                    f"type={type(exc).__name__} "
                    f"error={exc}"
                ),
            )

    # -------------------------------------------------
    # SHARED FALLBACK
    # -------------------------------------------------

    self.debug(
        "CAT",
        "USING_SHARED_FALLBACK",
    )

    try:
        await send_fallback_image(
            self,
            event,
        )

        self.debug(
            "CAT",
            "SUCCESS source=fallback",
        )
        return

    except Exception as exc:
        self.debug(
            "FALLBACK",
            (
                f"FAILED "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

    try:
        await event.reply(
            "متأسفانه نتونستم تصویر گربه رو ارسال کنم."
        )

    except Exception:
        pass


# ---------------------------------------------------------
# CAT COMMAND
# ---------------------------------------------------------

@command(
    name="گربه",
    permission="everyone",
    chat_type="all",
    description="یک عکس تصادفی از گربه می‌فرستد.",
    native_name="cat",
)
async def cat(
    self,
    event,
) -> None:
    await _run_cat(
        self,
        event,
    )


# ---------------------------------------------------------
# CAT TEXT TRIGGER
# ---------------------------------------------------------

@on_event(
    events.NewMessage(incoming=True)
)
async def on_cat_trigger(
    self,
    event,
) -> None:
    text = (
        event.raw_text or ""
    ).strip()

    if not text:
        return

    if self.command_manager.is_command_message(
        text
    ):
        return

    if not matches_trigger_words(
        text,
        CAT_TRIGGER_WORDS,
        max_words=5,
    ):
        return

    if await should_skip_trigger_on_bot_reply(
        self,
        event,
    ):
        return

    await _run_cat(
        self,
        event,
    )