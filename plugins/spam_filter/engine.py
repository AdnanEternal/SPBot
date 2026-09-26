from dataclasses import dataclass
from difflib import SequenceMatcher
import re


SUSPICIOUS_THRESHOLD = 35
SPAM_THRESHOLD = 60
HARD_SCORE_THRESHOLD = 85

NEW_USER_1_HOUR = 3600
NEW_USER_6_HOURS = 6 * 3600
NEW_USER_24_HOURS = 24 * 3600

WEIGHTS = {
    "flood": 30,
    "repeat": 25,
    "similarity": 20,
    "links": 15,
    "char_flood": 10,
}

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(slots=True)
class SpamFeatures:
    link_count: int
    repeat_count: int
    recent_message_count: int

    similarity: float

    char_flood: bool

    flood_score: int
    repeat_score: int
    similarity_score: int
    link_score: int
    char_flood_score: int


@dataclass(slots=True)
class SpamDecision:
    level: str
    score: int
    reason: str = ""
    hard_rule: str | None = None


def _clamp(value: float) -> int:
    return int(
        max(
            0,
            min(
                100,
                round(value),
            ),
        )
    )


def _threshold_score(
    value: int,
    threshold: int,
) -> int:
    if threshold <= 0 or value <= threshold:
        return 0

    if value >= threshold * 2:
        return 100

    progress = (
        value - threshold
    ) / max(
        1,
        threshold,
    )

    return _clamp(
        35 + progress * 65
    )


def normalize_text(
    text: str,
) -> str:
    text = _WHITESPACE_RE.sub(
        " ",
        text.strip().lower(),
    )

    return _NON_WORD_RE.sub(
        "",
        text,
    )


def calculate_similarity(
    text: str,
    recent_texts: list[str],
) -> tuple[float, int]:
    normalized = normalize_text(text)

    if len(normalized) < 6:
        return 0.0, 0

    best = 0.0

    for previous in recent_texts:
        previous_normalized = normalize_text(
            previous
        )

        if (
            len(previous_normalized) < 6
            or previous_normalized == normalized
        ):
            continue

        ratio = SequenceMatcher(
            None,
            normalized,
            previous_normalized,
        ).ratio()

        best = max(
            best,
            ratio,
        )

    if best >= 0.92:
        signal = 90
    elif best >= 0.85:
        signal = 70
    elif best >= 0.75:
        signal = 45
    elif best >= 0.65:
        signal = 25
    else:
        signal = 0

    return best, signal


def build_features(
    *,
    text: str,
    repeat_count: int,
    recent_message_count: int,
    recent_texts: list[str],
    link_count: int,
    char_flood: bool,
    flood_threshold: int,
    repeat_threshold: int,
    link_threshold: int,
) -> SpamFeatures:
    similarity, similarity_score = (
        calculate_similarity(
            text,
            recent_texts,
        )
    )

    return SpamFeatures(
        link_count=link_count,
        repeat_count=repeat_count,
        recent_message_count=recent_message_count,
        similarity=similarity,
        char_flood=char_flood,
        flood_score=_threshold_score(
            recent_message_count,
            flood_threshold,
        ),
        repeat_score=_threshold_score(
            repeat_count,
            repeat_threshold,
        ),
        similarity_score=similarity_score,
        link_score=_threshold_score(
            link_count,
            link_threshold,
        ),
        char_flood_score=(
            100
            if char_flood
            else 0
        ),
    )

def calculate_score(
    features: SpamFeatures,
    context: dict | None = None,
) -> int:
    score = (
        features.flood_score
        * WEIGHTS["flood"]
        / 100
        +
        features.repeat_score
        * WEIGHTS["repeat"]
        / 100
        +
        features.similarity_score
        * WEIGHTS["similarity"]
        / 100
        +
        features.link_score
        * WEIGHTS["links"]
        / 100
        +
        features.char_flood_score
        * WEIGHTS["char_flood"]
        / 100
    )

    context = context or {}

    external = context.get(
        "external_signals",
        {},
    )

    try:
        external_bonus = int(
            external.get(
                "score_bonus",
                0,
            )
        )
    except (TypeError, ValueError):
        external_bonus = 0

    score += max(
        0,
        min(
            30,
            external_bonus,
        ),
    )

    if context.get(
        "is_new_user"
    ):
        join_age = context.get(
            "join_age_seconds"
        )

        if (
            join_age is not None
            and score >= 15
        ):
            if join_age <= 3600:
                score += 15
            elif join_age <= 6 * 3600:
                score += 10
            elif join_age <= 24 * 3600:
                score += 6

    # web.splus.ir حساسیت بالاتری دارد.
    # لینک‌های عادی همچنان امتیاز می‌گیرند.
    # splus.ir/meet عمداً هیچ امتیاز پروفایلی نمی‌گیرد.
    if context.get(
        "profile_has_splus_web_link"
    ):
        score += 10

    elif context.get(
        "profile_has_other_link"
    ):
        score += 4

    return _clamp(score)

def evaluate_hard_rules(
    *,
    features: SpamFeatures,
    context: dict,
    score: int,
) -> tuple[str, str] | None:

    external = context.get(
        "external_signals",
        {},
    )

    # قانون سفارشی Bio
    matched_bio_rules = context.get(
        "matched_bio_rules",
        [],
    )

    if matched_bio_rules:
        patterns = [
            str(rule["pattern"])
            for rule in matched_bio_rules
        ]

        return (
            "custom_bio_rule",
            "مطابقت با قانون سفارشی Bio: "
            + "، ".join(patterns),
        )

    if external.get("hard_spam"):
        return (
            "external_hard_spam",
            "یک قانون خارجی، اسپم شدید را تأیید کرد",
        )

    if (
        external.get(
            "content_filter_match"
        )
        and score >= 25
    ):
        return (
            "content_filter_plus_spam",
            "پیام هم رفتار اسپمی داشت و هم با Content Filter مطابقت داشت",
        )

    # فقط لینک‌هایی که واقعاً سیگنال ضداسپم دارند
    # می‌توانند این قانون را فعال کنند.
    #
    # splus.ir/meet عمداً در اینجا وارد نمی‌شود.
    profile_has_actionable_link = (
        context.get(
            "profile_has_splus_web_link"
        )
        or context.get(
            "profile_has_other_link"
        )
    )

    if (
        context.get("is_new_user")
        and profile_has_actionable_link
        and features.link_count > 0
    ):
        return (
            "new_user_profile_link",
            "کاربر تازه‌وارد با لینک پروفایل، پیام لینک‌دار ارسال کرد",
        )

    if (
        features.flood_score >= 80
        and (
            features.repeat_score >= 70
            or
            features.similarity_score >= 70
        )
    ):
        return (
            "flood_plus_repetition",
            "فلاد شدید همراه با تکرار یا شباهت زیاد پیام‌ها",
        )

    return None

def decide(
    *,
    features: SpamFeatures,
    context: dict,
) -> SpamDecision:
    score = calculate_score(
        features,
        context,
    )

    hard_rule = evaluate_hard_rules(
        features=features,
        context=context,
        score=score,
    )

    if hard_rule is not None:
        name, reason = hard_rule

        return SpamDecision(
            level="HARD_SPAM",
            score=score,
            reason=reason,
            hard_rule=name,
        )

    if score >= HARD_SCORE_THRESHOLD:
        return SpamDecision(
            level="HARD_SPAM",
            score=score,
            reason="امتیاز رفتار اسپمی بسیار بالا بود",
        )

    if score >= SPAM_THRESHOLD:
        return SpamDecision(
            level="SPAM",
            score=score,
            reason="رفتار کاربر با الگوی اسپم مطابقت داشت",
        )

    if score >= SUSPICIOUS_THRESHOLD:
        return SpamDecision(
            level="SUSPICIOUS",
            score=score,
            reason="رفتار کاربر مشکوک به اسپم بود",
        )

    return SpamDecision(
        level="NORMAL",
        score=score,
    )