import re

_URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+", re.IGNORECASE)

# اگه یه کاراکتر بیشتر از این تعداد پشت‌سرهم تکرار بشه، اسپم حساب می‌شه
# (مثلاً «سلاممممممممممم» یا «!!!!!!!!!!!!!!!»). ثابته و از تنظیمات هر
# گروه جدا نگه داشته شده که تعداد کامندهای قابل‌تنظیم زیادی نشه.
_MAX_CHAR_RUN = 10


def count_links(text: str) -> int:
    return len(_URL_RE.findall(text))


def has_char_flood(text: str) -> bool:
    run_char = ""
    run_length = 0
    for ch in text:
        if ch == run_char:
            run_length += 1
        else:
            run_char = ch
            run_length = 1
        if run_length > _MAX_CHAR_RUN:
            return True
    return False
