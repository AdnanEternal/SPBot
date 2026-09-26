import re


_URL_RE = re.compile(
    r"https?://\S+|www\.\S+|t\.me/\S+",
    re.IGNORECASE,
)

_MAX_CHAR_RUN = 280


def has_char_flood(
    text: str,
) -> bool:
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
def extract_links(
    text: str,
) -> list[str]:
    return _URL_RE.findall(
        text or ""
    )


def is_whitelisted_url(
    url: str,
    whitelist: list[str],
) -> bool:
    url_lower = url.casefold()

    return any(
        pattern.casefold() in url_lower
        for pattern in whitelist
        if pattern
    )


def count_links(
    text: str,
    whitelist: list[str] | None = None,
) -> int:
    links = extract_links(text)

    if not whitelist:
        return len(links)

    return sum(
        not is_whitelisted_url(
            url,
            whitelist,
        )
        for url in links
    )

