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

def _gregorian_to_jalali(
    gy: int,
    gm: int,
    gd: int,
) -> tuple[int, int, int]:
    g_days_in_month = [
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31,
    ]

    gy -= 1600
    gm -= 1
    gd -= 1

    g_day_no = (
        365 * gy
        + (gy + 3) // 4
        - (gy + 99) // 100
        + (gy + 399) // 400
    )

    for i in range(gm):
        g_day_no += g_days_in_month[i]

    if (
        gm > 1
        and (
            (gy + 1600) % 4 == 0
            and (
                (gy + 1600) % 100 != 0
                or (gy + 1600) % 400 == 0
            )
        )
    ):
        g_day_no += 1

    g_day_no += gd

    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = (
        979
        + 33 * j_np
        + 4 * (j_day_no // 1461)
    )

    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (
            j_day_no - 1
        ) // 365

        j_day_no = (
            j_day_no - 1
        ) % 365

    if j_day_no < 186:
        jm = (
            1
            + j_day_no // 31
        )

        jd = (
            1
            + j_day_no % 31
        )

    else:
        jm = (
            7
            + (j_day_no - 186) // 30
        )

        jd = (
            1
            + (j_day_no - 186) % 30
        )

    return jy, jm, jd


def format_project_jalali_date(
    value: datetime,
) -> str:
    local = to_project_timezone(
        value
    )

    jy, jm, jd = _gregorian_to_jalali(
        local.year,
        local.month,
        local.day,
    )

    return (
        f"{jy:04d}/{jm:02d}/{jd:02d}"
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