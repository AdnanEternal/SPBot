import re
from typing import Optional


def extract_trigger_text(text: str, trigger: str) -> Optional[str]:
    text = (text or '').strip()
    trigger = (trigger or '').strip()
    if not text or not trigger:
        return None
    match = re.search(rf'(?<!\\w){re.escape(trigger)}(?!\\w)', text, re.I | re.U)
    if match is None:
        return None
    cleaned = (text[:match.start()] + ' ' + text[match.end():]).strip()
    return cleaned or 'سلام'
