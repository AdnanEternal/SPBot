from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


# شواهد قدیمی بعد از این مدت دیگر برای تأیید اسپمر بودن
# اهمیت زیادی ندارند.
OBSERVATION_WINDOW_SECONDS = 45

# برای اینکه دو رفتار مستقل را "هم‌زمان" در نظر بگیریم.
CONFIRMATION_WINDOW_SECONDS = 30

# بعد از تأیید، همان incident را دوباره مجازات نکن.
CONFIRMED_COOLDOWN_SECONDS = 120

MAX_OBSERVATIONS = 32


@dataclass(slots=True, frozen=True)
class SpamObservation:
    timestamp: float
    level: str
    score: int
    signals: frozenset[str]
    hard_rule: str | None


@dataclass(slots=True, frozen=True)
class ConfirmationResult:
    is_confirmed: bool
    confirmed_now: bool
    confidence: int
    reason: str


class SpamConfirmationTracker:
    """
    تشخیص می‌دهد که آیا رفتارهای اخیر یک کاربر
    برای تأیید اسپمر بودن کافی هستند یا نه.

    این کلاس قرار نیست مجازات کند.
    فقط Evidence جمع می‌کند.
    """

    def __init__(self) -> None:
        self._observations = defaultdict(
            lambda: deque(
                maxlen=MAX_OBSERVATIONS
            )
        )

        self._confirmed_until: dict[
            tuple[int, int],
            float,
        ] = {}

    @staticmethod
    def _signals(
        features,
    ) -> frozenset[str]:

        signals: set[str] = set()

        if getattr(
            features,
            "flood_score",
            0,
        ) >= 70:
            signals.add("flood")

        if getattr(
            features,
            "repeat_score",
            0,
        ) >= 70:
            signals.add("repeat")

        if getattr(
            features,
            "similarity_score",
            0,
        ) >= 70:
            signals.add("similarity")

        if getattr(
            features,
            "char_flood_score",
            0,
        ) >= 100:
            signals.add("char_flood")

        return frozenset(signals)

    def _clean(
        self,
        key: tuple[int, int],
        now: float,
    ) -> deque[SpamObservation]:

        observations = self._observations[key]

        cutoff = (
            now
            - OBSERVATION_WINDOW_SECONDS
        )

        while (
            observations
            and observations[0].timestamp < cutoff
        ):
            observations.popleft()

        confirmed_until = (
            self._confirmed_until.get(key)
        )

        if (
            confirmed_until is not None
            and confirmed_until <= now
        ):
            self._confirmed_until.pop(
                key,
                None,
            )

        return observations

    @staticmethod
    def _confidence(
        observations: list[SpamObservation],
    ) -> int:

        if not observations:
            return 0

        max_score = max(
            observation.score
            for observation in observations
        )

        unique_signals = set().union(
            *(
                observation.signals
                for observation in observations
            )
        )

        strong_count = len(observations)

        confidence = (
            50
            + int(max_score * 0.35)
            + min(
                20,
                len(unique_signals) * 8,
            )
            + min(
                20,
                max(
                    0,
                    strong_count - 1,
                ) * 10,
            )
        )

        return max(
            0,
            min(
                100,
                confidence,
            ),
        )

    def observe(
        self,
        group_id: int,
        user_id: int,
        decision,
        features,
    ) -> ConfirmationResult:

        now = time.monotonic()

        key = (
            group_id,
            user_id,
        )

        observations = self._clean(
            key,
            now,
        )

        # -------------------------------------------------
        # کاربر قبلاً در همین incident تأیید شده.
        # -------------------------------------------------

        confirmed_until = (
            self._confirmed_until.get(key)
        )

        if (
            confirmed_until is not None
            and confirmed_until > now
        ):
            return ConfirmationResult(
                is_confirmed=True,
                confirmed_now=False,
                confidence=95,
                reason=(
                    "کاربر در وضعیت تأییدشده‌ی فعلی است."
                ),
            )

        # -------------------------------------------------
        # Rule متنی به‌تنهایی ثابت نمی‌کند کاربر اسپمر است.
        # مثلاً یک کاربر عادی ممکن است یک عبارت ممنوع بفرستد.
        # -------------------------------------------------

        if decision.hard_rule == (
            "custom_text_rule"
        ):
            return ConfirmationResult(
                is_confirmed=False,
                confirmed_now=False,
                confidence=0,
                reason=(
                    "قانون متنی به‌تنهایی نشانه‌ی "
                    "اسپمر بودن نیست."
                ),
            )

        signals = self._signals(
            features
        )

        # هیچ نشانه‌ی رفتاری قابل اتکایی نداریم.
        if not signals:
            return ConfirmationResult(
                is_confirmed=False,
                confirmed_now=False,
                confidence=0,
                reason=(
                    "نشانه‌ی رفتاری کافی وجود ندارد."
                ),
            )

        observation = SpamObservation(
            timestamp=now,
            level=decision.level,
            score=max(
                0,
                min(
                    100,
                    int(decision.score),
                ),
            ),
            signals=signals,
            hard_rule=decision.hard_rule,
        )

        observations.append(
            observation
        )



        # -------------------------------------------------
        # رفتارهای خیلی واضح
        # -------------------------------------------------

        if decision.hard_rule in {
            "extreme_burst",
            "extreme_flood",
            "repeat_burst",
            "flood_plus_repetition",
        }:
            self._confirmed_until[key] = (
                now
                + CONFIRMED_COOLDOWN_SECONDS
            )

            confidence = (
                98
                if decision.hard_rule
                == "extreme_flood"
                else max(
                    92,
                    self._confidence(
                        list(observations)
                    ),
                )
            )

            return ConfirmationResult(
                is_confirmed=True,
                confirmed_now=True,
                confidence=confidence,
                reason=(
                    "الگوی رفتاری بسیار قوی "
                    "و قابل‌تأیید شناسایی شد."
                ),
            )

        # -------------------------------------------------
        # تأیید با چند رفتار مستقل
        # -------------------------------------------------

        cutoff = (
            now
            - CONFIRMATION_WINDOW_SECONDS
        )

        recent = [
            observation
            for observation in observations
            if observation.timestamp >= cutoff
        ]

        union = (
            set().union(
                *(
                    observation.signals
                    for observation in recent
                )
            )
            if recent
            else set()
        )

        total_score = sum(
            observation.score
            for observation in recent
        )

        flood_heavy = any(
            (
                "flood" in observation.signals
                and observation.score >= 25
            )
            for observation in recent
        )

        # دو رفتار نسبتاً قوی + دو نوع نشانه‌ی مستقل
        multi_signal_confirmation = (
            len(recent) >= 2
            and len(union) >= 2
            and total_score >= 120
        )

        # چند burst واقعی، مخصوصاً وقتی flood وجود داشته باشد.
        repeated_flood_confirmation = (
            len(recent) >= 3
            and len(union) >= 1
            and flood_heavy
            and total_score >= 80
        )

        if (
            multi_signal_confirmation
            or repeated_flood_confirmation
        ):
            self._confirmed_until[key] = (
                now
                + CONFIRMED_COOLDOWN_SECONDS
            )

            confidence = max(
                90,
                self._confidence(recent),
            )

            return ConfirmationResult(
                is_confirmed=True,
                confirmed_now=True,
                confidence=confidence,
                reason=(
                    "چند نشانه‌ی مستقل در یک "
                    "بازه‌ی کوتاه رفتار اسپمی "
                    "را تأیید کردند."
                ),
            )

        return ConfirmationResult(
            is_confirmed=False,
            confirmed_now=False,
            confidence=self._confidence(
                recent
            ),
            reason=(
                "برای تأیید، شواهد بیشتری لازم است."
            ),
        )

    def clear(
        self,
        group_id: int,
        user_id: int,
    ) -> None:

        key = (
            group_id,
            user_id,
        )

        self._observations.pop(
            key,
            None,
        )

        self._confirmed_until.pop(
            key,
            None,
        )