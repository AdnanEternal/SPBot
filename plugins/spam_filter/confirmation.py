from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


OBSERVATION_WINDOW_SECONDS = 45
CONFIRMATION_WINDOW_SECONDS = 30
CONFIRMED_COOLDOWN_SECONDS = 120

MAX_OBSERVATIONS = 32

# برای تأیید با چند نوع رفتار مستقل
MULTI_SIGNAL_MIN_OBSERVATIONS = 4
MULTI_SIGNAL_MIN_UNIQUE_SIGNALS = 2
MULTI_SIGNAL_MIN_TOTAL_SCORE = 180

# برای حالتی که فقط یک نوع رفتار دیده می‌شود
SINGLE_SIGNAL_MIN_OBSERVATIONS = 6
SINGLE_SIGNAL_MIN_TOTAL_SCORE = 450


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
    فقط مشخص می‌کند آیا شواهد کافی برای تأیید اسپم بودن
    کاربر وجود دارد یا نه.

    این کلاس خودش هیچ مجازاتی انجام نمی‌دهد.
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
        decision,
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
            "burst_score",
            0,
        ) >= 70:
            signals.add("burst")

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

        # اگر یک منبع خارجی صراحتاً hard_spam گفته،
        # آن را هم به‌عنوان evidence ثبت کن؛
        # ولی دیگر به‌تنهایی باعث confirmation نمی‌شود.
        if getattr(
            decision,
            "hard_rule",
            None,
        ) == "external_hard_spam":
            signals.add("external_hard_spam")

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

        observation_count = len(
            observations
        )

        confidence = (
            40
            + int(max_score * 0.35)
            + min(
                25,
                len(unique_signals) * 8,
            )
            + min(
                30,
                max(
                    0,
                    observation_count - 1,
                ) * 5,
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

        # ---------------------------------------------
        # قبلاً همین incident تأیید شده است.
        # ---------------------------------------------

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
                    "کاربر قبلاً در همین "
                    "incident تأیید شده است."
                ),
            )

        # ---------------------------------------------
        # قانون متنی مالک = spam confirmation نیست.
        # این مسیر در actions جداگانه مدیریت می‌شود.
        # ---------------------------------------------

        if decision.hard_rule == (
            "custom_text_rule"
        ):
            return ConfirmationResult(
                is_confirmed=False,
                confirmed_now=False,
                confidence=0,
                reason=(
                    "قانون متنی به‌تنهایی "
                    "اسپم بودن کاربر را ثابت نمی‌کند."
                ),
            )

        signals = self._signals(
            decision,
            features,
        )

        # هیچ evidence رفتاری نداریم.
        # مهم: حتی SPAM/HARD_SPAM هم دیگر
        # بدون evidence مستقیماً confirmed نمی‌شوند.
        if not signals:
            return ConfirmationResult(
                is_confirmed=False,
                confirmed_now=False,
                confidence=0,
                reason=(
                    "هیچ نشانه‌ی رفتاری کافی "
                    "برای تأیید وجود ندارد."
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

        # ---------------------------------------------
        # فقط observationهای بازه‌ی confirmation
        # ---------------------------------------------

        cutoff = (
            now
            - CONFIRMATION_WINDOW_SECONDS
        )

        recent = [
            item
            for item in observations
            if item.timestamp >= cutoff
        ]

        if not recent:
            return ConfirmationResult(
                is_confirmed=False,
                confirmed_now=False,
                confidence=0,
                reason="شواهد اخیر کافی نیست.",
            )

        union = set().union(
            *(
                item.signals
                for item in recent
            )
        )

        total_score = sum(
            item.score
            for item in recent
        )

        # ---------------------------------------------
        # حالت اول:
        # چند رفتار مستقل در چند پیام
        # ---------------------------------------------

        multi_signal_confirmation = (
            len(recent)
            >= MULTI_SIGNAL_MIN_OBSERVATIONS
            and len(union)
            >= MULTI_SIGNAL_MIN_UNIQUE_SIGNALS
            and total_score
            >= MULTI_SIGNAL_MIN_TOTAL_SCORE
        )

        # ---------------------------------------------
        # حالت دوم:
        # یک رفتار واحد ولی به‌شدت تکرارشده
        #
        # مثلاً flood شدید یا repeat شدید.
        # برای جلوگیری از false positive عمداً
        # evidence بیشتری لازم دارد.
        # ---------------------------------------------

        single_signal_confirmation = (
            len(recent)
            >= SINGLE_SIGNAL_MIN_OBSERVATIONS
            and total_score
            >= SINGLE_SIGNAL_MIN_TOTAL_SCORE
        )

        if (
            multi_signal_confirmation
            or single_signal_confirmation
        ):
            self._confirmed_until[key] = (
                now
                + CONFIRMED_COOLDOWN_SECONDS
            )

            confidence = max(
                90,
                self._confidence(recent),
            )

            if multi_signal_confirmation:
                reason = (
                    "چند نشانه‌ی مستقل در چند پیام "
                    "رفتار اسپمی را تأیید کردند."
                )
            else:
                reason = (
                    "یک الگوی رفتاری به‌شدت "
                    "و به‌صورت مکرر مشاهده شد."
                )

            return ConfirmationResult(
                is_confirmed=True,
                confirmed_now=True,
                confidence=confidence,
                reason=reason,
            )

        return ConfirmationResult(
            is_confirmed=False,
            confirmed_now=False,
            confidence=self._confidence(
                recent
            ),
            reason=(
                "برای تأیید اسپمر بودن، "
                "شواهد بیشتری لازم است."
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