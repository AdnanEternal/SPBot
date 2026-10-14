import os
import re
from pathlib import Path
from typing import Optional, Any


_ENV_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$"
)
_ENV_REFERENCE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|-)([^}]*))?\}"
)
_DOUBLE_QUOTE_ESCAPES = {
    "\\": "\\",
    "'": "'",
    '"': '"',
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_SINGLE_QUOTE_ESCAPES = {"\\": "\\", "'": "'"}


def _closing_quote_index(value: str, quote: str) -> int:
    """Return the first non-escaped closing quote, or -1 if none exists."""
    for index in range(1, len(value)):
        if value[index] != quote:
            continue

        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and value[cursor] == "\\":
            backslashes += 1
            cursor -= 1

        if backslashes % 2 == 0:
            return index

    return -1


def _decode_quoted_value(value: str, quote: str) -> str:
    escapes = (
        _DOUBLE_QUOTE_ESCAPES
        if quote == '"'
        else _SINGLE_QUOTE_ESCAPES
    )

    def replace_escape(match: re.Match[str]) -> str:
        character = match.group(1)
        return escapes.get(character, match.group(0))

    return re.sub(r"\\(.)", replace_escape, value)


def _expand_env_references(value: str) -> str:
    """Expand ${NAME}, ${NAME:-default}, and ${NAME-default}."""
    def replace_reference(match: re.Match[str]) -> str:
        name, operator, default = match.groups()
        current = os.environ.get(name)

        if operator == ":-":
            return current if current else (default or "")
        if operator == "-" and current is None:
            return default or ""

        return current if current is not None else ""

    return _ENV_REFERENCE.sub(replace_reference, value)


def _load_env_file() -> None:
    """
    Load the project's .env file without third-party dependencies.

    Variables already supplied by the operating system/hosting platform win.
    """
    env_path = Path(__file__).resolve().parent / ".env"

    try:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return

    line_index = 0

    while line_index < len(lines):
        line_number = line_index + 1
        line = lines[line_index].strip()
        line_index += 1

        if not line or line.startswith("#"):
            continue

        match = _ENV_LINE.match(line)
        if not match:
            continue

        key, raw_value = match.groups()
        raw_value = raw_value.strip()
        interpolate = True

        if raw_value.startswith(("'", '"')):
            quote = raw_value[0]
            combined_value = raw_value
            closing_index = _closing_quote_index(combined_value, quote)

            while closing_index < 0 and line_index < len(lines):
                combined_value += "\n" + lines[line_index]
                line_index += 1
                closing_index = _closing_quote_index(combined_value, quote)

            if closing_index < 0:
                raise ValueError(
                    f"فایل .env: کوتیشن مقدار متغیر '{key}' "
                    f"که از خط {line_number} شروع شده بسته نشده است."
                )

            trailing = combined_value[closing_index + 1:].strip()
            if trailing and not trailing.startswith("#"):
                raise ValueError(
                    f"فایل .env: مقدار نامعتبر برای '{key}' "
                    f"در خط {line_number}."
                )

            raw_value = _decode_quoted_value(
                combined_value[1:closing_index],
                quote,
            )
            interpolate = quote == '"'

        else:
            if raw_value.startswith("#"):
                raw_value = ""
            else:
                raw_value = re.split(r"\s+#", raw_value, maxsplit=1)[0].rstrip()

        if interpolate:
            raw_value = _expand_env_references(raw_value)

        # Match load_dotenv()'s default behavior: do not override host env vars.
        if key not in os.environ:
            os.environ[key] = raw_value


class Config:
    _instance = None
    _loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._loaded:
            _load_env_file()
            self._loaded = True

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        value = os.getenv(key)
        if value is None and default is not None:
            return default
        if value is None:
            raise ValueError(f"❌ متغیر محیطی '{key}' یافت نشد!")
        return value

    def get_required(self, key: str) -> str:
        """
        دریافت متغیری که حتما باید وجود داشته باشد در غیر این صورت خطا می‌دهد.
        """
        return self.get(key)


# یک نمونه‌ی سراسری برای استفاده در کل پروژه
config = Config()
