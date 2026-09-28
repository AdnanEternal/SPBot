

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
