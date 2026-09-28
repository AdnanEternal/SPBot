from dataclasses import dataclass
from difflib import SequenceMatcher
import math
import re


SUSPICIOUS_THRESHOLD = 35
SPAM_THRESHOLD = 60
HARD_SCORE_THRESHOLD = 85
EXTREME_FLOOD_MULTIPLIER = 3
EXTREME_BURST_WINDOW_SECONDS = 3
EXTREME_BURST_COUNT = 10


WEIGHTS = {
    "flood": 25,
    "burst": 20,
    "repeat": 10,
    "similarity": 20,
    "char_flood": 10,
}

# Repeat is evidence, not a decision threshold.
# The curve grows continuously and slowly, then saturates.
REPEAT_EVIDENCE_SCALE = 35.0

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(slots=True)
class SpamFeatures:
    repeat_count: int
    recent_message_count: int

    burst_message_count: int
    burst_score: int
    
    similarity: float

    char_flood: bool

    flood_score: int
    repeat_score: int
    similarity_score: int
    char_flood_score: int


@dataclass(slots=True)
class SpamDecision:
    level: str
    score: int
    reason: str = ""
    hard_rule: str | None = None


def _clamp(
    value: float,
) -> int:
    return int(
        max(
            0,
            min(
                100,
                round(value),
            ),
        )
    )

def _repeat_evidence_score(
    repeat_count: int,
    repeat_reference: int,
) -> int:
    """Map repeated identical messages to a small, continuous evidence score."""

    if repeat_count <= 1:
        return 0

    reference = max(
        1,
        int(repeat_reference),
    )

    excess = max(
        0,
        repeat_count - reference,
    )

    return _clamp(
        100.0
        * (
            1.0
            - math.exp(
                -excess
                / REPEAT_EVIDENCE_SCALE,
            )
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


def adaptive_flood_threshold(
    base_threshold: int,
    join_age_seconds: float | None,
    *,
    trust_score: float = 0.0,
    user_origin: str = "UNKNOWN",
    is_new_user: bool = False,
) -> int:

    if base_threshold <= 0:
        return base_threshold

    trust_score = max(
        0.0,
        min(
            100.0,
            float(trust_score),
        ),
    )

    if is_new_user:
        age_multiplier = 1.0

    elif user_origin == "UNOBSERVED_JOIN":
        # We do not know the real membership age.
        # Keep a conservative but non-new-user threshold.
        age_multiplier = 1.25

    elif join_age_seconds is None:
        age_multiplier = 1.0

    elif join_age_seconds < 60 * 60:
        age_multiplier = 1.0

    elif join_age_seconds < 24 * 60 * 60:
        age_multiplier = 1.25

    elif join_age_seconds < 7 * 24 * 60 * 60:
        age_multiplier = 1.50

    elif join_age_seconds < 30 * 24 * 60 * 60:
        age_multiplier = 1.75

    else:
        age_multiplier = 2.0

    trust_bonus = trust_score / 100.0

    multiplier = min(
        3.0,
        age_multiplier + trust_bonus,
    )

    return max(
        base_threshold,
        int(
            round(
                base_threshold * multiplier
            )
        ),
    )


def calculate_similarity(
    text: str,
    recent_texts: list[str],
) -> tuple[float, int]:
    normalized = normalize_text(
        text
    )

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
        text, 
        repeat_count, 
        recent_message_count, 
        burst_message_count,
        recent_texts,
        char_flood, 
        flood_threshold, 
        repeat_threshold
    ):

    should_calculate_similarity = (
        recent_message_count >= 3
        and bool(recent_texts)
        and len(text.strip()) >= 10
        and (
            repeat_count >= 2
            or recent_message_count > flood_threshold
        )
    )

    if should_calculate_similarity:
        similarity, similarity_score = calculate_similarity(
            text,
            recent_texts,
        )
    else:
        similarity, similarity_score = 0.0, 0

    return SpamFeatures(
    repeat_count=repeat_count,
    recent_message_count=recent_message_count,
    burst_message_count=burst_message_count,
    similarity=similarity,
    char_flood=char_flood,
    flood_score=_threshold_score(
        recent_message_count,
        flood_threshold,
    ),
    burst_score=(
        100
        if burst_message_count >= 10
        else _threshold_score(
            burst_message_count,
            6,
        )
    ),
    repeat_score=_repeat_evidence_score(
        repeat_count,
        repeat_threshold,
    ),
    similarity_score=similarity_score,
    char_flood_score=100 if char_flood else 0,
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
        features.burst_score
        * WEIGHTS["burst"]
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
    except (
        TypeError,
        ValueError,
    ):
        external_bonus = 0

    score += max(
        0,
        min(
            30,
            external_bonus,
        ),
    )



    return _clamp(score)


def evaluate_hard_rules(
    *,
    features: SpamFeatures,
    context: dict,
    score: int,
) -> tuple[str, str] | None:

    matched_rules = context.get(
        "matched_text_rules",
        [],
    )

    # فقط تطابق داخل خود پیام می‌تواند
    # باعث حذف همان پیام شود.
    #
    # تطابق داخل profile نباید باعث حذف
    # پیام عادی کاربر شود.
    message_rules = [
        rule
        for rule in matched_rules
        if rule.get("source") == "message"
    ]

    if message_rules:
        first = message_rules[0]

        return (
            "custom_text_rule",
            (
                "مطابقت با قانون سفارشی: "
                f"{first['pattern']} "
                f"(source={first['source']})"
            ),
        )

    external = context.get(
        "external_signals",
        {},
    )

    if external.get("hard_spam"):
        return (
            "external_hard_spam",
            "یک قانون خارجی، اسپم شدید را تأیید کرد",
        )

    # Content Filter + رفتار اسپمی
    # توسط Content Filter مدیریت می‌شود.
    if (
        external.get("content_filter_match")
        and score >= 25
    ):
        return (
            "content_filter_plus_spam",
            (
                "پیام هم رفتار اسپمی داشت "
                "و هم با Content Filter مطابقت داشت"
            ),
        )

    # Flood فوق‌العاده شدید
    if (
        features.burst_message_count
        >= EXTREME_BURST_COUNT
    ):
        return (
            "extreme_burst",
            (
                "تعداد بسیار زیادی پیام "
                "در چند ثانیه ارسال شد"
            ),
        )

    flood_threshold = max(
        1,
        int(
            context.get(
                "flood_threshold",
                5,
            )
        ),
    )

    base_flood_threshold = max(
        1,
        int(
            context.get(
                "base_flood_threshold",
                5,
            )
        ),
    )

    extreme_flood_count = max(
        12,
        base_flood_threshold
        * EXTREME_FLOOD_MULTIPLIER,
    )

    if (
        features.recent_message_count
        >= extreme_flood_count
    ):
        return (
            "extreme_flood",
            (
                "تعداد بسیار زیادی پیام "
                "در بازه‌ی کوتاه ارسال شد"
            ),
        )

    # تکرار شدید
    repeat_burst_count = max(
        6,
        flood_threshold * 2,
    )

    if (
        features.repeat_count
        >= repeat_burst_count
        and features.recent_message_count
        >= max(
            6,
            flood_threshold,
        )
    ):
        return (
            "repeat_burst",
            (
                "تعداد زیادی پیام یکسان "
                "در بازه‌ی کوتاه ارسال شد"
            ),
        )

    # Flood + تکرار / شباهت
    if (
        features.flood_score >= 80
        and (
            features.repeat_score >= 70
            or features.similarity_score >= 70
        )
    ):
        return (
            "flood_plus_repetition",
            (
                "فلاد شدید همراه با تکرار "
                "یا شباهت زیاد پیام‌ها"
            ),
        )

    return None


def calculate_violation_score(
    decision: SpamDecision,
    context: dict | None = None,
) -> int:

    if decision.level not in (
        "SPAM",
        "HARD_SPAM",
    ):
        return 0

    context = context or {}

    user_state = str(
        context.get(
            "user_state",
            "",
        )
    ).upper()

    # Rule محتواییِ مشترک با Content Filter
    # قبلاً توسط Content Filter ثبت شده است.
    if decision.hard_rule == (
        "content_filter_plus_spam"
    ):
        return 0

    # Rule متنیِ مالک فقط باید باعث حذف پیام شود،
    # نه مجازات کاربر به‌عنوان اسپمر.
    if decision.hard_rule == (
        "custom_text_rule"
    ):
        return 1

    # رفتارهای واقعاً شدید، حتی برای کاربر قدیمی،
    # همچنان تخلف شدید باقی می‌مانند.
    if decision.hard_rule in {
        "extreme_burst",
        "extreme_flood",
        "external_hard_spam",
    }:
        return 8

    if decision.hard_rule == (
        "repeat_burst"
    ):
        severity = 8

    elif decision.hard_rule == (
        "flood_plus_repetition"
    ):
        severity = 7

    else:
        severity = max(
            1,
            round(
                (
                    decision.score - 50
                ) / 5
            ),
        )

        severity = max(
            1,
            min(
                10,
                severity,
            ),
        )

    # کاربر قدیمی را برای الگوهای عادیِ اسپم
    # وارد مسیر مجازات شدید نکن.
    # بات‌های واقعی همچنان از extreme_* عبور می‌کنند.
    if (
        user_state == "ESTABLISHED"
        and decision.hard_rule in {
            "repeat_burst",
            "flood_plus_repetition",
        }
    ):
        severity = min(
            severity,
            5,
        )

    elif (
        user_state == "ESTABLISHED"
        and decision.hard_rule is None
    ):
        severity = min(
            severity,
            5,
        )

    return max(
        1,
        min(
            10,
            severity,
        ),
    )
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

        # این‌ها تخلف هستند، ولی به‌تنهایی اثبات
        # نمی‌کنند که کاربر اسپمر است.
        if name in {
            "custom_text_rule",
            "content_filter_plus_spam",
        }:
            return SpamDecision(
                level="SPAM",
                score=max(
                    score,
                    60,
                ),
                reason=reason,
                hard_rule=name,
            )

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