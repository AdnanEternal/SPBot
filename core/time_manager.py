from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import config


PROJECT_TIMEZONE_KEY = "PROJECT_TIMEZONE"

DEFAULT_TIMEZONE_NAME = "Asia/Tehran"
FALLBACK_TIMEZONE_NAME = "UTC"


def _resolve_timezone(
    timezone_name: str,
) -> ZoneInfo:
    """
    یک timezone معتبر IANA برمی‌گرداند.

    این تابع فقط برای timezoneهای صریح استفاده می‌شود.
    اگر timezone نامعتبر باشد، خطا می‌دهد تا اشتباه
    برنامه‌نویس پنهان نشود.
    """

    try:
        return ZoneInfo(timezone_name)

    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"منطقه زمانی نامعتبر است: "
            f"{timezone_name}"
        ) from exc


def _load_project_timezone() -> tuple[str, ZoneInfo]:
    """
    timezone اصلی پروژه را تعیین می‌کند.

    ترتیب:
    1. PROJECT_TIMEZONE از config/.env
    2. اگر تنظیم نشده بود: Asia/Tehran
    3. اگر timezone انتخاب‌شده قابل بارگذاری نبود: UTC
    """

    timezone_name = str(
        config.get(
            PROJECT_TIMEZONE_KEY,
            DEFAULT_TIMEZONE_NAME,
        )
    ).strip()

    if not timezone_name:
        timezone_name = DEFAULT_TIMEZONE_NAME

    try:
        return (
            timezone_name,
            _resolve_timezone(
                timezone_name
            ),
        )

    except ValueError:
        print(
            "⚠️ منطقه زمانی پروژه قابل بارگذاری نبود: "
            f"{timezone_name}\n"
            f"🌍 استفاده از {FALLBACK_TIMEZONE_NAME}"
        )

        fallback = _resolve_timezone(
            FALLBACK_TIMEZONE_NAME
        )

        return (
            FALLBACK_TIMEZONE_NAME,
            fallback,
        )


PROJECT_TIMEZONE_NAME, PROJECT_TIMEZONE = (
    _load_project_timezone()
)


def get_project_timezone_name() -> str:
    """
    نام timezone اصلی پروژه را برمی‌گرداند.

    مثال:
        Asia/Tehran
    """

    return PROJECT_TIMEZONE_NAME


def get_project_timezone() -> ZoneInfo:
    """
    timezone اصلی پروژه را برمی‌گرداند.
    """

    return PROJECT_TIMEZONE


def now():
    """
    زمان فعلی پروژه را برمی‌گرداند.

    زمان مبنا همیشه UTC است و سپس به timezone
    پروژه تبدیل می‌شود.

    خروجی timezone-aware است.
    """

    return datetime.now(
        timezone.utc
    ).astimezone(
        PROJECT_TIMEZONE
    )


def now_utc():
    """
    زمان فعلی UTC.

    خروجی timezone-aware است.
    """

    return datetime.now(
        timezone.utc
    )


def now_in(
    timezone_name: str,
):
    """
    زمان فعلی را در timezone دلخواه برمی‌گرداند.

    مثال:
        now_in("Asia/Baku")
        now_in("Europe/London")
        now_in("America/New_York")

    اگر timezone نامعتبر باشد، ValueError می‌دهد.
    """

    target_timezone = _resolve_timezone(
        timezone_name
    )

    return datetime.now(
        timezone.utc
    ).astimezone(
        target_timezone
    )