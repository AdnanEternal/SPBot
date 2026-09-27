from dataclasses import dataclass
from difflib import SequenceMatcher
import re


SUSPICIOUS_THRESHOLD = 35
SPAM_THRESHOLD = 60
HARD_SCORE_THRESHOLD = 85

WEIGHTS = {
    "flood": 30,
    "repeat": 25,
    "similarity": 25,
    "char_flood": 20,
}

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(slots=True)
class SpamFeatures:
    repeat_count: int
    recent_message_count: int

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
) -> int:
    """
    هرچه کاربر قدیمی‌تر باشد، Flood Threshold بالاتر می‌رود.

    هدف:
    کاربر واقعی با چند پیام سریع تنبیه نشود،
    ولی رباتی که ده‌ها پیام پشت‌سرهم می‌فرستد همچنان خیلی سریع شناسایی شود.
    """
    if base_threshold <= 0:
        return base_threshold

    if join_age_seconds is None:
        multiplier = 1.0

    elif join_age_seconds < 3600:
        # کمتر از ۱ ساعت
        multiplier = 1.0

    elif join_age_seconds < 24 * 3600:
        # ۱ ساعت تا ۱ روز
        multiplier = 1.25

    elif join_age_seconds < 7 * 24 * 3600:
        # ۱ تا ۷ روز
        multiplier = 1.5

    elif join_age_seconds < 30 * 24 * 3600:
        # ۷ تا ۳۰ روز
        multiplier = 2.0

    else:
        # بالای ۳۰ روز
        multiplier = 3.0

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
        recent_texts,
        char_flood, 
        flood_threshold, 
        repeat_threshold
    ):

    # فقط وقتی چند پیام پشت‌سرهم داریم مقایسه‌ی شباهت معنی داره؛
    # برای ترافیک عادی هزینه‌ی SequenceMatcher رو نمی‌دیم.
    if recent_message_count >= 2 and recent_texts:
        similarity, similarity_score = calculate_similarity(text, recent_texts)
    else:
        similarity, similarity_score = 0.0, 0

    return SpamFeatures(
        repeat_count=repeat_count,
        recent_message_count=recent_message_count,
        similarity=similarity,
        char_flood=char_flood,
        flood_score=_threshold_score(recent_message_count, flood_threshold),
        repeat_score=_threshold_score(repeat_count, repeat_threshold),
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

    # ---------------------------------------------
    # Rule متنی، به‌تنهایی = spammer نیست
    # ---------------------------------------------

    if matched_rules:
        first = matched_rules[0]

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

    # ---------------------------------------------
    # Content Filter + رفتار اسپمی
    # به‌تنهایی نباید مستقیم مجازات ایجاد کند.
    # ---------------------------------------------

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

    # ---------------------------------------------
    # Flood فوق‌العاده شدید
    # ---------------------------------------------

    flood_threshold = max(
        1,
        int(
            context.get(
                "flood_threshold",
                5,
            )
        ),
    )

    extreme_flood_count = max(
        12,
        flood_threshold * 3,
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

    # ---------------------------------------------
    # تکرار شدید
    # ---------------------------------------------

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

    # ---------------------------------------------
    # Flood + تکرار / شباهت
    # ---------------------------------------------

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
) -> int:

    if decision.level not in (
        "SPAM",
        "HARD_SPAM",
    ):
        return 0

    # Ruleهای محتوایی به‌تنهایی
    # نباید به مجازات سنگین برسند.
    if decision.hard_rule == (
        "custom_text_rule"
    ):
        return 1

    if decision.hard_rule == (
        "content_filter_plus_spam"
    ):
        return 2

    # رفتارهای خیلی واضح
    if decision.hard_rule == (
        "extreme_flood"
    ):
        return 8

    if decision.hard_rule == (
        "repeat_burst"
    ):
        return 8

    if decision.hard_rule == (
        "flood_plus_repetition"
    ):
        return 7

    # تبدیل score رفتار به severity
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

    return severity

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