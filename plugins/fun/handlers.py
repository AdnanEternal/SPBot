
from __future__ import annotations

import asyncio
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
    count_words,
    find_trigger_words,
    guess_file_extension,
    is_image_response,
    is_media_response,
    send_fallback_image,
    send_media_bytes,
)

from pathlib import Path


# =========================================================
# CONFIGURATION
# =========================================================

CAT_API_URL = "https://cataas.com/cat"
DOG_API_URL = "https://random.dog/woof.json"

API_TIMEOUT = 10
MAX_MEDIA_BYTES = 15 * 1024 * 1024
MAX_MEDIA_CAPTION_CHARS = 1024

CAT_TRIGGER_WORDS = (
    "میو",
    "گربه",
    "پیشی",
)

DOG_TRIGGER_WORDS = (
    "سگ",
    "هاپو",
)

DOG_MEDIA_TIMEOUT = 20
MAX_DOG_MEDIA_BYTES = 30 * 1024 * 1024
# =========================================================
# CAT API
# =========================================================

def _find_url_in_payload(value) -> str | None:
    """استخراج URL از ساختارهای متداول پاسخ API گربه."""

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
    """پاسخ API گربه را به تصویر قابل ارسال تبدیل می‌کند."""

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

        return response.body, f"cat{extension}"

    image_url = None

    if response.is_json:
        try:
            image_url = _find_url_in_payload(
                response.json()
            )
        except ValueError:
            image_url = None

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
        timeout=API_TIMEOUT,
        max_bytes=MAX_MEDIA_BYTES,
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
    """تابع خصوصی دریافت عکس گربه؛ چیزی ارسال نمی‌کند."""

    try:
        response = await request_api(
            CAT_API_URL,
            timeout=API_TIMEOUT,
            max_bytes=MAX_MEDIA_BYTES,
        )

        image = await _resolve_cat_image(response)

        if image is None:
            self.debug("CAT_API", "NO_USABLE_IMAGE")

        return image

    except APIClientError as exc:
        self.debug(
            "CAT_API",
            f"FAILED type={type(exc).__name__} error={exc}",
        )

    except Exception as exc:
        self.debug(
            "CAT_API",
            f"UNEXPECTED_ERROR type={type(exc).__name__} error={exc}",
        )

    return None


# =========================================================
# DOG API
# =========================================================

async def _fetch_dog_media(
    self,
) -> tuple[bytes, str] | None:
    """
    تابع خصوصی دریافت رسانه سگ.

    random.dog می‌تواند تصویر، GIF یا ویدئو برگرداند.
    پاسخ JSON فقط URL رسانه را در اختیارمان می‌گذارد.
    """

    try:
        response = await request_api(
            DOG_API_URL,
            timeout=API_TIMEOUT,
            max_bytes=64 * 1024,
        )

        if not response.ok or not response.is_json:
            self.debug("DOG_API", "INVALID_API_RESPONSE")
            return None

        try:
            payload = response.json()
        except ValueError:
            self.debug("DOG_API", "INVALID_JSON")
            return None

        if not isinstance(payload, dict):
            self.debug("DOG_API", "INVALID_JSON_SHAPE")
            return None

        media_url = payload.get("url")

        if not isinstance(media_url, str):
            self.debug("DOG_API", "MEDIA_URL_MISSING")
            return None

        parsed_url = urlparse(media_url)

        # فقط میزبان مورد انتظار API پذیرفته می‌شود.
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "random.dog"
        ):
            self.debug("DOG_API", "UNEXPECTED_MEDIA_HOST")
            return None

        media_response = await request_api(
            media_url,
            timeout=DOG_MEDIA_TIMEOUT,
            max_bytes=MAX_DOG_MEDIA_BYTES,
        )

        if not media_response.ok:
            self.debug("DOG_API", "MEDIA_DOWNLOAD_FAILED")
            return None

        # redirect نباید فایل را به میزبان دیگری منتقل کند.
        final_url = urlparse(media_response.url)

        if final_url.hostname != "random.dog":
            self.debug("DOG_API", "UNEXPECTED_REDIRECT_HOST")
            return None

        if not is_media_response(
            media_response.content_type,
            media_response.body,
        ):
            self.debug("DOG_API", "UNSUPPORTED_MEDIA")
            return None

        # پسوند URL را در اولویت قرار می‌دهیم؛
        # ممکن است Content-Type سرور عمومی یا نادقیق باشد.
        extension = Path(
            urlparse(media_response.url).path
        ).suffix.lower()

        supported_extensions = {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".mp4",
            ".webm",
        }

        if extension not in supported_extensions:
            extension = guess_file_extension(
                media_response.content_type,
                media_response.body,
                url=media_response.url,
            )

        if extension not in supported_extensions:
            self.debug(
                "DOG_API",
                (
                    f"UNSUPPORTED_EXTENSION "
                    f"extension={extension} "
                    f"content_type={media_response.content_type}"
                ),
            )
            return None

        return (
            media_response.body,
            f"dog{extension}",
        )

    except APIClientError as exc:
        self.debug(
            "DOG_API",
            f"FAILED type={type(exc).__name__} error={exc}",
        )

    except Exception as exc:
        self.debug(
            "DOG_API",
            f"UNEXPECTED_ERROR type={type(exc).__name__} error={exc}",
        )

    return None


# =========================================================
# FEATURE-SPECIFIC TRIGGER POLICIES
# =========================================================

def _matches_short_trigger(
    self,
    event,
    trigger_words,
) -> bool:
    """
    سیاست فعلی مشترک گربه و سگ.

    این تابع سیاست اجرا را اعمال می‌کند؛
    find_trigger_words به تنهایی چنین تصمیمی نمی‌گیرد.
    """

    text = (event.raw_text or "").strip()

    if not text:
        return False

    if self.command_manager.is_command_message(text):
        return False

    if count_words(text) > 5:
        return False

    return bool(
        find_trigger_words(
            text,
            trigger_words,
        )
    )


def _matches_cat_trigger(
    self,
    event,
) -> bool:
    # سیاست گربه؛ در آینده می‌تواند مستقل تغییر کند.
    return _matches_short_trigger(
        self,
        event,
        CAT_TRIGGER_WORDS,
    )


def _matches_dog_trigger(
    self,
    event,
) -> bool:
    # سیاست سگ؛ در آینده می‌تواند مستقل تغییر کند.
    return _matches_short_trigger(
        self,
        event,
        DOG_TRIGGER_WORDS,
    )


def _find_triggered_feature(
    self,
    event,
) -> str | None:
    """
    قابلیت منطبق را بر اساس اولین تریگر در متن انتخاب می‌کند.

    ابتدا تریگر عمومی پیدا می‌شود، سپس سیاست همان قابلیت
    باید پیام را تأیید کند.
    """

    text = (event.raw_text or "").strip()

    if not text:
        return None

    if self.command_manager.is_command_message(text):
        return None

    all_triggers = (
        CAT_TRIGGER_WORDS
        + DOG_TRIGGER_WORDS
    )

    for word in find_trigger_words(
        text,
        all_triggers,
    ):
        if (
            word in CAT_TRIGGER_WORDS
            and _matches_cat_trigger(self, event)
        ):
            return "cat"

        if (
            word in DOG_TRIGGER_WORDS
            and _matches_dog_trigger(self, event)
        ):
            return "dog"

    return None


# =========================================================
# RESPONSE STATE
# =========================================================

def _get_media_state(
    self,
    event,
    feature: str,
) -> dict:
    """
    وضعیت اجرای قابلیت برای همین پیام.

    fetch هر قابلیت مستقل است، اما هماهنگی ارسال
    پاسخ میان آن‌ها مشترک است.
    """

    fetchers = {
        "cat": _fetch_cat_image,
        "dog": _fetch_dog_media,
    }

    fetcher = fetchers.get(feature)

    if fetcher is None:
        raise ValueError(
            f"Unknown Fun feature: {feature}"
        )

    states = getattr(
        event,
        "_fun_response_states",
        None,
    )

    if not isinstance(states, dict):
        states = {}
        event._fun_response_states = states

    state = states.get(feature)

    if state is None:
        state = {
            "feature": feature,
            "media_task": None,
            "completion": (
                asyncio.get_running_loop().create_future()
            ),
            "finalizing": False,
            "finalized": False,
            "sent_message": None,
            "delivery_ok": False,
        }

        states[feature] = state

    if (
        state["media_task"] is None
        and not state["finalized"]
    ):
        state["media_task"] = asyncio.create_task(
            fetcher(self)
        )

    return state


def _get_existing_media_state(
    event,
    feature: str | None = None,
) -> dict | None:
    states = getattr(
        event,
        "_fun_response_states",
        None,
    )

    if not isinstance(states, dict):
        return None

    if feature is not None:
        return states.get(feature)

    for state in states.values():
        if not state.get("finalized"):
            return state

    return None


async def _get_media(
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
    text = str(text or "")[:4000]

    try:
        sent = await event.reply(text)
        return True, sent

    except Exception:
        try:
            sent = await event.respond(text)
            return True, sent

        except Exception:
            return False, None


async def _try_send_media(
    self,
    event,
    media: tuple[bytes, str],
    *,
    caption: str = "",
) -> tuple[bool, object | None]:
    data, filename = media

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
                f"FAILED file={filename} "
                f"type={type(exc).__name__} error={exc}"
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
                f"FAILED type={type(exc).__name__} "
                f"error={exc}"
            ),
        )

        return False, None


# =========================================================
# SHARED RESPONSE DELIVERY
# =========================================================

async def _finish_media_response(
    self,
    event,
    state: dict,
    *,
    answer: str = "",
    ai_failed: bool = False,
    standalone: bool = False,
) -> object | None:
    """
    ارسال نهایی رسانه و پاسخ.

    standalone:
        فقط رسانه ارسال می‌شود؛ در صورت شکست API یا ارسال،
        fallback.jpg و سپس پیام متنی امتحان می‌شوند.

    AI موفق:
        رسانه با پاسخ AI ارسال می‌شود.
        اگر ارسال رسانه ممکن نبود، پاسخ AI متنی فرستاده می‌شود.

    AI ناموفق:
        رسانه یا fallback.jpg همراه پیام خطا ارسال می‌شود.
    """

    if state["finalized"]:
        return state["sent_message"]

    if state["finalizing"]:
        completion = state.get("completion")

        if completion is not None:
            await completion

        return state["sent_message"]

    state["finalizing"] = True

    sent = None
    delivery_ok = False

    feature = state["feature"]

    media_label = (
        "گربه"
        if feature == "cat"
        else "سگ"
    )

    try:
        media = await _get_media(state)

        # -------------------------------------------------
        # A. فقط رسانه
        # -------------------------------------------------

        if standalone:
            if media is not None:
                delivery_ok, sent = await _try_send_media(
                    self,
                    event,
                    media,
                )

            if not delivery_ok:
                delivery_ok, sent = await _try_send_fallback(
                    self,
                    event,
                )

            if not delivery_ok:
                delivery_ok, sent = await _send_text(
                    event,
                    (
                        f"متأسفانه نتونستم رسانه‌ی "
                        f"{media_label} رو ارسال کنم."
                    ),
                )

        # -------------------------------------------------
        # B. خطای تولید پاسخ AI
        # -------------------------------------------------

        elif ai_failed:
            caption = _media_caption(answer)

            if media is not None:
                delivery_ok, sent = await _try_send_media(
                    self,
                    event,
                    media,
                    caption=caption,
                )

            if not delivery_ok:
                delivery_ok, sent = await _try_send_fallback(
                    self,
                    event,
                    caption=caption,
                )

            if not delivery_ok:
                delivery_ok, sent = await _send_text(
                    event,
                    answer,
                )

        # -------------------------------------------------
        # C. پاسخ موفق AI
        # -------------------------------------------------

        else:
            if media is not None:
                delivery_ok, sent = await _try_send_media(
                    self,
                    event,
                    media,
                    caption=_media_caption(answer),
                )

            # اگر رسانه آماده یا قابل ارسال نبود،
            # پاسخ تولیدشده‌ی AI را از دست نمی‌دهیم.
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
                f"type={type(exc).__name__} error={exc}"
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


async def _send_standalone_media(
    self,
    event,
    feature: str,
) -> None:
    state = _get_media_state(
        self,
        event,
        feature,
    )

    await _finish_media_response(
        self,
        event,
        state,
        standalone=True,
    )


# =========================================================
# COMMANDS
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
    await _send_standalone_media(
        self,
        event,
        "cat",
    )


@command(
    name="سگ",
    permission="everyone",
    chat_type="all",
    description="یک رسانه تصادفی از سگ می‌فرستد.",
    native_name="dog",
)
async def dog(
    self,
    event,
) -> None:
    await _send_standalone_media(
        self,
        event,
        "dog",
    )


# =========================================================
# AI RESPONSE OWNERSHIP
# =========================================================

@on_bus_event("response_composition_prepare")
async def prepare_response_composition(
    self,
    event,
    context: dict,
) -> None:
    """
    AI Gateway پیش از درخواست مدل این رویداد را می‌فرستد.

    Fun فقط وقتی مالکیتی قبلاً گرفته نشده باشد،
    می‌تواند تحویل پاسخ را به عهده بگیرد.
    """

    if context.get("response_owner") is not None:
        return

    feature = _find_triggered_feature(
        self,
        event,
    )

    if feature is None:
        return

    # دریافت رسانه هم‌زمان با تولید پاسخ AI آغاز می‌شود.
    _get_media_state(
        self,
        event,
        feature,
    )

    context["response_owner"] = "fun"
    context["response_data"] = {
        "feature": feature,
    }
    event._fun_response_owned = True

@on_bus_event("response_composition_success")
async def finalize_response_composition(
    self,
    event,
    context: dict,
    answer: str,
) -> None:
    if context.get("response_owner") != "fun":
        return

    response_data = (
        context.get("response_data") or {}
    )

    feature = response_data.get("feature")

    if feature not in {"cat", "dog"}:
        return

    state = _get_existing_media_state(
        event,
        feature,
    )

    if state is None:
        state = _get_media_state(
            self,
            event,
            feature,
        )

    sent = await _finish_media_response(
        self,
        event,
        state,
        answer=answer,
    )

    context["sent_message"] = sent
    context["delivery_completed"] = state["delivery_ok"]


@on_bus_event("response_composition_failure")
async def fail_response_composition(
    self,
    event,
    context: dict,
    error_text: str,
) -> None:
    if context.get("response_owner") != "fun":
        return

    response_data = (
        context.get("response_data") or {}
    )

    feature = response_data.get("feature")

    if feature not in {"cat", "dog"}:
        return

    state = _get_existing_media_state(
        event,
        feature,
    )

    if state is None:
        state = _get_media_state(
            self,
            event,
            feature,
        )

    sent = await _finish_media_response(
        self,
        event,
        state,
        answer=error_text,
        ai_failed=True,
    )

    context["sent_message"] = sent
    context["delivery_completed"] = state["delivery_ok"]


@on_bus_event("response_composition_not_requested")
async def finalize_without_ai(
    self,
    event,
) -> None:
    """
    AI Gateway تصمیم گرفته که این پیام اصلاً پاسخ AI ندارد.

    اگر Fun قبلاً وضعیت رسانه را ساخته باشد، آن را مستقل می‌فرستد.
    اگر هنوز وضعیت وجود نداشته باشد، رویداد بی‌اثر است و
    on_media_trigger در ادامه مسیر مستقل را اجرا می‌کند.
    """

    state = _get_existing_media_state(event)

    if state is None or state["finalized"]:
        return

    await _finish_media_response(
        self,
        event,
        state,
        standalone=True,
    )


# =========================================================
# MESSAGE TRIGGERS
# =========================================================

@on_event(
    events.NewMessage(incoming=True)
)
async def on_media_trigger(
    self,
    event,
) -> None:
    feature = _find_triggered_feature(
        self,
        event,
    )

    if feature is None:
        return

    state = _get_media_state(
        self,
        event,
        feature,
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

    if ai_processed:
        if not state["finalized"]:
            # اگر AI اصلاً پاسخی تولید نکرده،
            # رسانه باید مستقل ارسال شود.
            if not ai_expected:
                await _finish_media_response(
                    self,
                    event,
                    state,
                    standalone=True,
                )

            # اگر Fun مالک پاسخ بوده اما هماهنگی کامل نشده،
            # مسیر مستقل راه بازیابی است.
            elif getattr(
                event,
                "_fun_response_owned",
                False,
            ):
                await _finish_media_response(
                    self,
                    event,
                    state,
                    standalone=True,
                )

        return
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
        # به Gateway فرصت می‌دهیم مشخص کند این پیام AI دارد
        # یا باید از رویداد response_composition_not_requested
        # برای ارسال مستقل رسانه استفاده شود.
        return

    await _finish_media_response(
        self,
        event,
        state,
        standalone=True,
    )