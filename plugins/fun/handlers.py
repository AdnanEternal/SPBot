from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Callable
from pathlib import Path

import aiohttp

import re

from splusthon import events

from core.decorators import command, on_event
from core.soroush_media import send_media
from plugins.fun.cat_cache import CatCache


CAT_API_URL = "https://cataas.com/cat"
CAT_API_TIMEOUT = 10

FALLBACK_IMAGE = (
    Path(__file__).parent / "fallback_cat.jpg"
)

cat_cache = CatCache()


DebugLogger = Callable[[str, str], None]


def _detect_extension(
    content_type: str,
    data: bytes,
) -> str | None:
    content_type = (
        content_type
        .lower()
        .split(";", 1)[0]
        .strip()
    )

    if (
        content_type == "image/jpeg"
        or data.startswith(b"\xff\xd8\xff")
    ):
        return ".jpg"

    if (
        content_type == "image/png"
        or data.startswith(
            b"\x89PNG\r\n\x1a\n"
        )
    ):
        return ".png"

    if (
        content_type == "image/gif"
        or data.startswith(b"GIF87a")
        or data.startswith(b"GIF89a")
    ):
        return ".gif"

    if (
        content_type == "image/webp"
        or (
            data.startswith(b"RIFF")
            and data[8:12] == b"WEBP"
        )
    ):
        return ".webp"

    return None


async def _download_cat(
    debug: DebugLogger | None = None,
) -> tuple[bytes, str] | None:
    started = time.perf_counter()

    if debug is not None:
        debug(
            "API",
            (
                f"START "
                f"url={CAT_API_URL} "
                f"timeout={CAT_API_TIMEOUT}s"
            ),
        )

    timeout = aiohttp.ClientTimeout(
        total=CAT_API_TIMEOUT
    )

    try:
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.get(
                CAT_API_URL
            ) as response:

                elapsed = (
                    time.perf_counter()
                    - started
                )

                content_type = response.headers.get(
                    "Content-Type",
                    "",
                )

                if debug is not None:
                    debug(
                        "API",
                        (
                            f"RESPONSE "
                            f"status={response.status} "
                            f"content_type={content_type or '-'} "
                            f"elapsed={elapsed:.3f}s"
                        ),
                    )

                if response.status != 200:
                    if debug is not None:
                        debug(
                            "API",
                            (
                                f"FAIL "
                                f"reason=http_status "
                                f"status={response.status}"
                            ),
                        )

                    return None

                data = await response.read()

                if debug is not None:
                    debug(
                        "API",
                        (
                            f"DOWNLOAD "
                            f"bytes={len(data)} "
                            f"elapsed="
                            f"{time.perf_counter() - started:.3f}s"
                        ),
                    )

                if not data:
                    if debug is not None:
                        debug(
                            "API",
                            "FAIL reason=empty_body",
                        )

                    return None

                extension = _detect_extension(
                    content_type,
                    data,
                )

                if extension is None:
                    if debug is not None:
                        debug(
                            "API",
                            (
                                "FAIL "
                                "reason=invalid_image "
                                f"bytes={len(data)}"
                            ),
                        )

                    return None

                filename = f"cat{extension}"

                if debug is not None:
                    debug(
                        "API",
                        (
                            f"SUCCESS "
                            f"file={filename} "
                            f"bytes={len(data)} "
                            f"total_elapsed="
                            f"{time.perf_counter() - started:.3f}s"
                        ),
                    )

                return data, filename

    except asyncio.TimeoutError:
        elapsed = (
            time.perf_counter()
            - started
        )

        if debug is not None:
            debug(
                "API",
                (
                    f"TIMEOUT "
                    f"after={elapsed:.3f}s "
                    f"limit={CAT_API_TIMEOUT}s"
                ),
            )

        return None

    except aiohttp.ClientError as exc:
        elapsed = (
            time.perf_counter()
            - started
        )

        if debug is not None:
            debug(
                "API",
                (
                    f"ERROR "
                    f"type={type(exc).__name__} "
                    f"elapsed={elapsed:.3f}s "
                    f"message={exc}"
                ),
            )

        return None

    except Exception as exc:
        elapsed = (
            time.perf_counter()
            - started
        )

        if debug is not None:
            debug(
                "API",
                (
                    f"UNEXPECTED_ERROR "
                    f"type={type(exc).__name__} "
                    f"elapsed={elapsed:.3f}s "
                    f"message={exc}"
                ),
            )

        return None


def _file_from_bytes(
    data: bytes,
    filename: str,
) -> io.BytesIO:
    file = io.BytesIO(data)
    file.name = filename
    return file


async def _send_bytes(
    client,
    chat_id,
    data: bytes,
    filename: str,
    reply_to: int,
    *,
    source: str,
    debug: DebugLogger | None = None,
) -> None:
    if debug is not None:
        debug(
            "SEND",
            (
                f"START "
                f"source={source} "
                f"file={filename} "
                f"bytes={len(data)}"
            ),
        )

    await send_media(
        client,
        chat_id,
        _file_from_bytes(
            data,
            filename,
        ),
        caption="",
        reply_to=reply_to,
    )

    if debug is not None:
        debug(
            "SEND",
            (
                f"SUCCESS "
                f"source={source} "
                f"file={filename}"
            ),
        )


def _load_fallback(
    debug: DebugLogger | None = None,
) -> tuple[bytes, str]:
    if debug is not None:
        debug(
            "FALLBACK",
            (
                f"LOAD_START "
                f"path={FALLBACK_IMAGE}"
            ),
        )

    data = FALLBACK_IMAGE.read_bytes()

    if debug is not None:
        debug(
            "FALLBACK",
            (
                f"LOAD_SUCCESS "
                f"file={FALLBACK_IMAGE.name} "
                f"bytes={len(data)}"
            ),
        )

    return data, FALLBACK_IMAGE.name


CAT_TRIGGER_WORDS = (
    "میو",
    "گربه",
    "پیشی",
)

CAT_TRIGGER_RE = re.compile(
    r"(?<!\w)("
    + "|".join(map(re.escape, CAT_TRIGGER_WORDS))
    + r")(?!\w)",
    re.UNICODE | re.IGNORECASE,
)


async def _run_cat(self, event) -> None:
    """منطق مشترک کامند و تریگر."""
    debug = self.debug

    debug(
        "REQUEST",
        (
            f"START "
            f"group={event.chat_id} "
            f"user={event.sender_id} "
            f"message={event.id}"
        ),
    )

    # ---------------------------------------------------------
    # 1. API
    # ---------------------------------------------------------
    downloaded = await _download_cat(debug)

    if downloaded is not None:
        data, filename = downloaded

        debug(
            "CACHE",
            (
                f"ADD_CANDIDATE "
                f"file={filename} "
                f"bytes={len(data)}"
            ),
        )

        cat_cache.add(
            data,
            filename,
            debug=debug,
        )

        try:
            await _send_bytes(
                self.client,
                event.chat_id,
                data,
                filename,
                event.id,
                source="api",
                debug=debug,
            )

            debug(
                "REQUEST",
                "SUCCESS source=api",
            )
            return

        except Exception as exc:
            debug(
                "SEND",
                (
                    f"FAILED "
                    f"source=api "
                    f"type={type(exc).__name__} "
                    f"message={exc}"
                ),
            )

    # ---------------------------------------------------------
    # 2. CACHE
    # ---------------------------------------------------------
    debug(
        "CACHE",
        (
            f"FALLBACK_START "
            f"count={cat_cache.count} "
            f"bytes={cat_cache.total_bytes} "
            f"limit_images=3 "
            f"limit_bytes=4194304"
        ),
    )

    cache_attempts = cat_cache.count

    for attempt in range(1, cache_attempts + 1):
        cached = cat_cache.get_random(
            debug=debug,
        )

        if cached is None:
            debug(
                "CACHE",
                (
                    f"ATTEMPT={attempt} "
                    "result=EMPTY"
                ),
            )
            break

        debug(
            "CACHE",
            (
                f"ATTEMPT={attempt} "
                f"key={cached.key[:8]} "
                f"file={cached.filename} "
                f"bytes={len(cached.data)}"
            ),
        )

        try:
            await _send_bytes(
                self.client,
                event.chat_id,
                cached.data,
                cached.filename,
                event.id,
                source="cache",
                debug=debug,
            )

            debug(
                "REQUEST",
                (
                    f"SUCCESS "
                    f"source=cache "
                    f"attempt={attempt}"
                ),
            )
            return

        except Exception as exc:
            debug(
                "SEND",
                (
                    f"FAILED "
                    f"source=cache "
                    f"attempt={attempt} "
                    f"type={type(exc).__name__} "
                    f"message={exc}"
                ),
            )

            cat_cache.remove(
                cached.key,
                debug=debug,
            )

    # ---------------------------------------------------------
    # 3. STATIC FALLBACK
    # ---------------------------------------------------------
    debug(
        "FALLBACK",
        "CACHE_EXHAUSTED switching_to_static_fallback",
    )

    try:
        fallback_data, fallback_filename = (
            _load_fallback(debug)
        )

        await _send_bytes(
            self.client,
            event.chat_id,
            fallback_data,
            fallback_filename,
            event.id,
            source="static_fallback",
            debug=debug,
        )

        debug(
            "REQUEST",
            "SUCCESS source=static_fallback",
        )
        return

    except Exception as exc:
        debug(
            "FALLBACK",
            (
                f"FAILED "
                f"type={type(exc).__name__} "
                f"message={exc}"
            ),
        )

    # ---------------------------------------------------------
    # 4. آخرین حالت ممکن
    # ---------------------------------------------------------
    debug(
        "REQUEST",
        "FAILED all_fallbacks_exhausted",
    )

    await event.reply(
        "متأسفانه خطایی رخ داد!",
        reply_to=event.id,
    )

@command(
    name="گربه",
    permission="everyone",
    chat_type="all",
    description="یک عکس تصادفی از گربه می‌فرستد.",
    native_name="cat",
)
async def cat(self, event) -> None:
    await _run_cat(self, event)


@on_event(events.NewMessage(incoming=True))
async def on_cat_trigger(self, event) -> None:
    text = (event.raw_text or "").strip()

    if not text:
        return

    if self.command_manager.is_command_message(text):
        return

    if CAT_TRIGGER_RE.search(text) is None:
        return

    await _run_cat(self, event)