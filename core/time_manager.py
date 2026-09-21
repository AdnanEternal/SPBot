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
    try:
        return ZoneInfo(timezone_name)

    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"منطقه زمانی نامعتبر است: "
            f"{timezone_name}"
        ) from exc


def _load_project_timezone() -> tuple[str, ZoneInfo]:
    """
    ترتیب انتخاب timezone:

    1. PROJECT_TIMEZONE
    2. Asia/Tehran
    3. در صورت شکست کامل: UTC
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

        return (
            FALLBACK_TIMEZONE_NAME,
            _resolve_timezone(
                FALLBACK_TIMEZONE_NAME
            ),
        )


PROJECT_TIMEZONE_NAME, PROJECT_TIMEZONE = (
    _load_project_timezone()
)


def get_project_timezone_name() -> str:
    return PROJECT_TIMEZONE_NAME


def get_project_timezone() -> ZoneInfo:
    return PROJECT_TIMEZONE


def now() -> datetime:
    """
    زمان فعلی پروژه.

    مثال:
        Asia/Tehran
    """

    return datetime.now(
        timezone.utc
    ).astimezone(
        PROJECT_TIMEZONE
    )


def now_utc() -> datetime:
    """
    زمان فعلی UTC.
    """

    return datetime.now(
        timezone.utc
    )


def now_in(
    timezone_name: str,
) -> datetime:
    """
    زمان فعلی در timezone دلخواه.

    مثال:
        now_in("Asia/Baku")
        now_in("Europe/London")
    """

    target_timezone = _resolve_timezone(
        timezone_name
    )

    return datetime.now(
        timezone.utc
    ).astimezone(
        target_timezone
    )


def to_project_timezone(
    value: datetime,
) -> datetime:
    """
    یک datetime موجود را به timezone پروژه تبدیل می‌کند.

    اگر datetime بدون timezone باشد، UTC فرض می‌شود.
    """

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        PROJECT_TIMEZONE
    )


def format_project_time(
    value: datetime,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """
    datetime را با timezone پروژه به رشته تبدیل می‌کند.
    """

    return to_project_timezone(
        value
    ).strftime(fmt)