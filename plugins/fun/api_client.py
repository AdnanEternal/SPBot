from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping

import aiohttp


DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RESPONSE_BYTES = 15 * 1024 * 1024


class APIClientError(RuntimeError):
    """خطای ارسال درخواست یا دریافت پاسخ API."""


class APIResponseTooLarge(APIClientError):
    """اندازه پاسخ از سقف تعیین‌شده بیشتر است."""


@dataclass(slots=True, frozen=True)
class APIResponse:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def content_type(self) -> str:
        value = self.headers.get(
            "Content-Type",
            "",
        )
        return value.split(";", 1)[0].strip().lower()

    @property
    def is_json(self) -> bool:
        return (
            "json" in self.content_type
        )

    def text(self) -> str:
        content_type = self.headers.get(
            "Content-Type",
            "",
        )

        encoding = "utf-8"

        for part in content_type.split(";")[1:]:
            key, separator, value = part.strip().partition("=")

            if (
                separator
                and key.strip().lower() == "charset"
            ):
                encoding = value.strip().strip('"\'')
                break

        try:
            return self.body.decode(
                encoding,
                errors="replace",
            )
        except LookupError:
            return self.body.decode(
                "utf-8",
                errors="replace",
            )

    def json(self) -> Any:
        return json.loads(
            self.text()
        )


async def request_api(
    url: str,
    *,
    method: str = "GET",
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    data: Any = None,
    json_data: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int | None = DEFAULT_MAX_RESPONSE_BYTES,
) -> APIResponse:
    """
    درخواست عمومی HTTP.

    این تابع هیچ فرضی درباره نوع پاسخ ندارد.
    پاسخ را به صورت bytes نگه می‌دارد و اطلاعات
    وضعیت، هدرها و آدرس نهایی را ارائه می‌کند.

    تفسیر JSON، متن، HTML، تصویر یا ویدئو
    بر عهده قابلیت فراخواننده است.

    max_bytes=None محدودیت اندازه را غیرفعال می‌کند؛
    فقط برای APIهای مورداعتماد استفاده شود.
    """

    if (
        max_bytes is not None
        and max_bytes < 1
    ):
        raise ValueError(
            "max_bytes must be positive or None."
        )

    timeout_config = aiohttp.ClientTimeout(
        total=timeout
    )

    try:
        async with aiohttp.ClientSession(
            timeout=timeout_config,
        ) as session:

            async with session.request(
                method=method.upper(),
                url=url,
                params=params,
                headers=headers,
                data=data,
                json=json_data,
                allow_redirects=True,
            ) as response:

                chunks: list[bytes] = []
                total_size = 0

                async for chunk in response.content.iter_chunked(
                    64 * 1024
                ):
                    total_size += len(chunk)

                    if (
                        max_bytes is not None
                        and total_size > max_bytes
                    ):
                        raise APIResponseTooLarge(
                            "API response exceeded "
                            f"the {max_bytes}-byte limit."
                        )

                    chunks.append(chunk)

                return APIResponse(
                    url=str(response.url),
                    status_code=response.status,
                    headers=dict(response.headers),
                    body=b"".join(chunks),
                )

    except APIResponseTooLarge:
        raise

    except asyncio.TimeoutError as exc:
        raise APIClientError(
            "API request timed out."
        ) from exc

    except aiohttp.ClientError as exc:
        raise APIClientError(
            f"API request failed: {type(exc).__name__}"
        ) from exc