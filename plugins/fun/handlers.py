
from __future__ import annotations

import asyncio
import json

from urllib.parse import urlparse

from splusthon import events

from core.decorators import (
    command,
    on_bus_event,
    on_event,
)

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
)


# =========================================================
# CAT CONFIGURATION
# =========================================================

CAT_API_URL = "https://cataas.com/cat"

CAT_API_TIMEOUT = 10

CAT_MAX_RESPONSE_BYTES = 15 * 1024 * 1024

MAX_MEDIA_CAPTION_CHARS = 1024

CAT_TRIGGER_WORDS = (
    "میو",
    "گربه",
    "پیشی",
)


# =========================================================
# CAT API RESPONSE PARSING
# =========================================================

def _find_url_in_payload(
    value,
) -> str | None:
    """
    استخراج URL از پاسخ JSON.

    ساختار JSON می‌تواند متفاوت باشد.
    این منطق مخصوص پاسخ API گربه است؛
    در api_client.py قرار نمی‌گیرد.
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
            if key not in value:
                continue

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
    تفسیر پاسخ API گربه.

    پشتیبانی:
        - تصویر مستقیم
        - JSON حاوی URL
        - متن ساده‌ای که خودش URL است

    پاسخ‌های دیگر برای این قابلیت قابل استفاده نیستند.
    """

    if not response.ok:
        return None

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

    if response.is_json:
        try:
            payload = response.json()

        except ValueError:
            payload = None

        if payload is not None:
            image_url = _find_url_in_payload(
                payload
            )

    elif response.content_type.startswith("text/"):
        candidate = response.text().strip()

        if candidate.startswith(
            ("https://", "http://")
        ):
            image_url = candidate

    if not image_url:
        return None

    image_response = await request_api(
        image_url,
        timeout=CAT_API_TIMEOUT,
        max_bytes=CAT_MAX_RESPONSE_BYTES,
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


async def _fetch_cat_image(
    self,
) -> tuple[bytes, str] | None:
    """
    فقط عکس را از API تهیه می‌کند.

    این تابع چیزی ارسال نمی‌کند و فال‌بک هم ندارد؛
    بنابراین می‌تواند هم‌زمان با درخواست AI اجرا شود.
    """

    try:
        response = await request_api(
            CAT_API_URL,
            timeout=CAT_API_TIMEOUT,
            max_bytes=CAT_MAX_RESPONSE_BYTES,
        )

        image = await _resolve_cat_image(response)

        if image is None:
            self.debug(
                "CAT_API",
                "NO_USABLE_IMAGE",
            )

        return image

    except APIClientError as exc:
        self.debug(
            "CAT_API",
            (
                f"FAILED "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

    except Exception as exc:
        self.debug(
            "CAT_API",
            (
                f"UNEXPECTED_ERROR "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

    return None


# =========================================================
# CAT-SPECIFIC TRIGGER POLICY
# =========================================================

def _matches_cat_trigger(
    self,
    event,
) -> bool:
    text = (
        event.raw_text or ""
    ).strip()

    if not text:
        return False

    if self.command_manager.is_command_message(text):
        return False

    return matches_trigger_words(
        text,
        CAT_TRIGGER_WORDS,
        max_words=5,
    )


# =========================================================
# RESPONSE STATE
# =========================================================

def _get_cat_state(
    self,
    event,
) -> dict:
    """
    وضعیت پاسخ این پیام را نگه می‌دارد تا callbackهای
    AI Gateway و Fun بتوانند روی یک کار مشترک هماهنگ شوند.
    """

    states = getattr(
        event,
        "_fun_response_states",
        None,
    )

    if not isinstance(states, dict):
        states = {}

        event._fun_response_states = states

    state = states.get("cat")

    if state is None:
        state = {
            "feature": "cat",
            "media_task": None,
            "completion": (
                asyncio.get_running_loop().create_future()
            ),
            "finalizing": False,
            "finalized": False,
            "sent_message": None,
            "delivery_ok": False,
        }

        states["cat"] = state

    if (
        state["media_task"] is None
        and not state["finalized"]
    ):
        state["media_task"] = asyncio.create_task(
            _fetch_cat_image(self)
        )

    return state


def _get_existing_cat_state(
    event,
) -> dict | None:
    states = getattr(
        event,
        "_fun_response_states",
        None,
    )

    if not isinstance(states, dict):
        return None

    return states.get("cat")


async def _get_cat_image(
    state: dict,
) -> tuple[bytes, str] | None:
    task = state.get("media_task")

    if task is None:
        return None

    try:
        return await task

    except Exception:
        return None


# =========================================================
# SEND HELPERS
# =========================================================

def _media_caption(
    text: str,
) -> str:
    """
    متن کامل پاسخ AI در حافظه باقی می‌ماند؛
    فقط کپشن رسانه به طول محافظه‌کارانه محدود می‌شود.
    """

    text = str(text or "")

    if len(text) <= MAX_MEDIA_CAPTION_CHARS:
        return text

    return (
        text[:MAX_MEDIA_CAPTION_CHARS - 1]
        + "…"
    )


async def _send_text(
    event,
    text: str,
) -> tuple[bool, object | None]:
    text = str(text or "")

    try:
        sent = await event.reply(
            text[:4000]
        )

        return True, sent

    except Exception:
        try:
            sent = await event.respond(
                text[:4000]
            )

            return True, sent

        except Exception:
            return False, None


async def _try_send_media(
    self,
    event,
    image: tuple[bytes, str],
    *,
    caption: str = "",
) -> tuple[bool, object | None]:
    data, filename = image

    try:
        sent = await send_media_bytes(
            self,
            event,
            data,
            filename,
            caption=caption,
        )

        return True, sent

    except Exception as exc:
        self.debug(
            "MEDIA_SEND",
            (
                f"FAILED "
                f"file={filename} "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

        return False, None


async def _try_send_fallback(
    self,
    event,
    *,
    caption: str = "",
) -> tuple[bool, object | None]:
    try:
        sent = await send_fallback_image(
            self,
            event,
            caption=caption,
        )

        return True, sent

    except Exception as exc:
        self.debug(
            "FALLBACK",
            (
                f"FAILED "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

        return False, None


# =========================================================
# RESPONSE FINALIZATION
# =========================================================

async def _finish_cat_response(
    self,
    event,
    state: dict,
    *,
    answer: str = "",
    ai_failed: bool = False,
    standalone: bool = False,
) -> object | None:
    """
    تصمیم نهایی بر اساس نتیجه‌ی API گربه و نتیجه‌ی AI.

    standalone:
        فقط عکس گربه خواسته شده؛ در صورت خطای API
        از فال‌بک مشترک استفاده می‌شود.

    AI موفق:
        عکس و کپشن؛ در صورت ناموفق بودن عکس،
        پاسخ AI به صورت متن ارسال می‌شود.

    AI ناموفق:
        عکس با کپشن خطای AI؛ اگر تهیه یا ارسال عکس
        ناموفق بود، تصویر fallback با همان کپشن ارسال می‌شود.
    """

    if state["finalized"]:
        return state["sent_message"]

    if state["finalizing"]:
        await state["completion"]
        return state["sent_message"]

    state["finalizing"] = True

    sent = None
    delivery_ok = False

    try:
        image = await _get_cat_image(state)

        # -------------------------------------------------
        # A. فقط عکس خواسته شده؛ AI پاسخی تولید نمی‌کند.
        # -------------------------------------------------

        if standalone:
            if image is not None:
                delivery_ok, sent = await _try_send_media(
                    self,
                    event,
                    image,
                )

            if not delivery_ok:
                delivery_ok, sent = await _try_send_fallback(
                    self,
                    event,
                )

            if not delivery_ok:
                delivery_ok, sent = await _send_text(
                    event,
                    "متأسفانه نتونستم تصویر گربه رو ارسال کنم.",
                )

        # -------------------------------------------------
        # B. AI خطا داده است.
        # -------------------------------------------------

        elif ai_failed:
            error_caption = _media_caption(answer)

            if image is not None:
                delivery_ok, sent = await _try_send_media(
                    self,
                    event,
                    image,
                    caption=error_caption,
                )

            if not delivery_ok:
                delivery_ok, sent = await _try_send_fallback(
                    self,
                    event,
                    caption=error_caption,
                )

            if not delivery_ok:
                delivery_ok, sent = await _send_text(
                    event,
                    answer,
                )

        # -------------------------------------------------
        # C. AI موفق بوده است.
        # -------------------------------------------------

        else:
            if image is not None:
                delivery_ok, sent = await _try_send_media(
                    self,
                    event,
                    image,
                    caption=_media_caption(answer),
                )

            # اگر عکس قابل ارسال نبود، پاسخ AI را
            # به‌صورت متن می‌فرستیم؛ فال‌بک لازم نیست.
            if not delivery_ok:
                delivery_ok, sent = await _send_text(
                    event,
                    answer,
                )

    except Exception as exc:
        self.debug(
            "RESPONSE",
            (
                f"FINALIZATION_ERROR "
                f"type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

    finally:
        state["sent_message"] = sent
        state["delivery_ok"] = delivery_ok
        state["finalizing"] = False
        state["finalized"] = True

        completion = state.get("completion")

        if (
            completion is not None
            and not completion.done()
        ):
            completion.set_result(sent)

    return sent


# =========================================================
# DIRECT CAT COMMAND
# =========================================================

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
    state = _get_cat_state(
        self,
        event,
    )

    await _finish_cat_response(
        self,
        event,
        state,
        standalone=True,
    )


# =========================================================
# GENERIC AI RESPONSE-COMPOSITION HOOKS
# =========================================================

@on_bus_event("response_composition_prepare")
async def prepare_response_composition(
    self,
    event,
    context: dict,
) -> None:
    """
    AI Gateway قبل از درخواست مدل این رویداد را می‌فرستد.

    هر قابلیت می‌تواند طبق سیاست مستقل خودش تصمیم بگیرد
    آیا پاسخ AI باید با رسانه ترکیب شود یا خیر.
    """

    if not _matches_cat_trigger(
        self,
        event,
    ):
        return

    state = _get_cat_state(
        self,
        event,
    )

    context["defer_response"] = True
    context["response_state"] = state


@on_bus_event("response_composition_success")
async def finalize_response_composition(
    self,
    event,
    context: dict,
    answer: str,
) -> None:
    if not context.get("defer_response"):
        return

    state = context.get(
        "response_state"
    )

    if state is None:
        return

    sent = await _finish_cat_response(
        self,
        event,
        state,
        answer=answer,
    )

    context["sent_message"] = sent
    context["delivery_completed"] = state[
        "delivery_ok"
    ]


@on_bus_event("response_composition_failure")
async def fail_response_composition(
    self,
    event,
    context: dict,
    error_text: str,
) -> None:
    if not context.get("defer_response"):
        return

    state = context.get(
        "response_state"
    )

    if state is None:
        return

    sent = await _finish_cat_response(
        self,
        event,
        state,
        answer=error_text,
        ai_failed=True,
    )

    context["sent_message"] = sent
    context["delivery_completed"] = state[
        "delivery_ok"
    ]


@on_bus_event("response_composition_not_requested")
async def finalize_without_ai(
    self,
    event,
) -> None:
    """
    اگر Fun تریگر را زودتر دیده باشد ولی مشخص شود
    این پیام اصلاً به AI نیاز ندارد، فقط عکس را ارسال می‌کند.

    اگر callback هوش مصنوعی زودتر اجرا شده باشد و هنوز
    هیچ state وجود نداشته باشد، این رویداد بی‌اثر است.
    """

    state = _get_existing_cat_state(event)

    if state is None or state["finalized"]:
        return

    await _finish_cat_response(
        self,
        event,
        state,
        standalone=True,
    )


# =========================================================
# CAT TRIGGER
# =========================================================

@on_event(
    events.NewMessage(incoming=True)
)
async def on_cat_trigger(
    self,
    event,
) -> None:
    if not _matches_cat_trigger(
        self,
        event,
    ):
        return

    state = _get_cat_state(
        self,
        event,
    )

    ai_processed = getattr(
        event,
        "_ai_gateway_processed",
        False,
    )

    ai_expected = getattr(
        event,
        "_ai_gateway_expected",
        False,
    )

    # AI Gateway قبلاً این پیام را پردازش کرده است.
    if ai_processed:
        if ai_expected and not state["finalized"]:
            # در حالت عادی AI قبلاً پاسخ ترکیبی را
            # نهایی کرده؛ این شاخه محافظی برای خطاهای
            # غیرمنتظره در مسیر هماهنگ‌سازی است.
            await _finish_cat_response(
                self,
                event,
                state,
                standalone=True,
            )

        elif not ai_expected:
            await _finish_cat_response(
                self,
                event,
                state,
                standalone=True,
            )

        return

    # اگر AI Gateway قبل از Fun اجرا شود، نتیجه‌ی پردازش
    # تا پایان callback مشخص است. اگر بعد از Fun اجرا شود،
    # این callback فقط دانلود عکس را شروع می‌کند و برمی‌گردد.
    plugin_manager = getattr(
        self,
        "plugin_manager",
        None,
    )

    ai_plugin = (
        plugin_manager.get_plugin_by_id("ai_gateway")
        if plugin_manager is not None
        else None
    )

    can_coordinate_with_ai = (
        event.is_group
        and event.sender_id is not None
        and ai_plugin is not None
        and ai_plugin.enabled
    )

    if can_coordinate_with_ai:
        return

    await _finish_cat_response(
        self,
        event,
        state,
        standalone=True,
    )