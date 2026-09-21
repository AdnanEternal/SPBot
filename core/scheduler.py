"""
زمان‌بندیِ اجرای کامند.

هر job یک کامند را با CommandManager.run(...) اجرا می‌کند؛ پس همه‌ی
امکانات run (chat_id، as_user، level، trusted، output، ...) اینجا هم
با همان نام‌ها کار می‌کنند:

    scheduler.daily("03:00", "دیتابیس بکاپ", trusted=True, output=Output.owners())
    scheduler.every(3600, "گیتهاب چک", trusted=True, output=Output.silent())
    scheduler.at(datetime(...), "پلاگین آپدیت", "violation_manager", level="owner")

نکته: باید از داخل event loop (مثلاً on_enable یا یک handler) صدا زده شود.
"""

from __future__ import annotations

import asyncio
import itertools
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from core.time_manager import PROJECT_TIMEZONE, now, now_utc

if TYPE_CHECKING:
    from core.command_manager import CommandManager

# فاصله‌ی تا اجرای بعدی (ثانیه)؛ None یعنی job تمام شده.
DelayFn = Callable[[], Optional[float]]


@dataclass
class ScheduledJob:
    id: str
    command: str
    args_text: str
    run_kwargs: dict[str, Any]
    owner: object | None = None
    task: asyncio.Task | None = None
    cancelled: bool = False


def _current_task() -> asyncio.Task | None:
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


class Scheduler:
    def __init__(self, commands: "CommandManager") -> None:
        self._commands = commands
        self._jobs: dict[str, ScheduledJob] = {}
        self._ids = itertools.count(1)

    # =========================================================
    # API عمومی
    # =========================================================

    def after(
        self,
        seconds: float,
        command: str,
        args_text: str = "",
        *,
        owner: object | None = None,
        **run_kwargs: Any,
    ) -> str:
        """یک بار، بعد از `seconds` ثانیه."""
        return self._add(
            command, args_text, run_kwargs, owner,
            self._once(lambda: float(seconds)),
        )

    def at(
        self,
        when: datetime,
        command: str,
        args_text: str = "",
        *,
        owner: object | None = None,
        **run_kwargs: Any,
    ) -> str:
        """
        یک بار، در زمان مشخص. datetime بدون timezone یعنی timezone پروژه.
        اگر زمان گذشته باشد، فوراً اجرا می‌شود.
        """
        if when.tzinfo is None:
            when = when.replace(tzinfo=PROJECT_TIMEZONE)

        def compute() -> float:
            return (when.astimezone(timezone.utc) - now_utc()).total_seconds()

        return self._add(command, args_text, run_kwargs, owner, self._once(compute))

    def every(
        self,
        seconds: float,
        command: str,
        args_text: str = "",
        *,
        immediately: bool = False,
        owner: object | None = None,
        **run_kwargs: Any,
    ) -> str:
        """هر `seconds` ثانیه؛ با immediately=True بار اول همین الان."""
        if seconds <= 0:
            raise ValueError("seconds باید بیشتر از صفر باشد.")

        first = True

        def next_delay() -> float:
            nonlocal first

            if first:
                first = False

                if immediately:
                    return 0.0

            return float(seconds)

        return self._add(command, args_text, run_kwargs, owner, next_delay)

    def daily(
        self,
        hhmm: str,
        command: str,
        args_text: str = "",
        *,
        owner: object | None = None,
        **run_kwargs: Any,
    ) -> str:
        """هر روز راس ساعت HH:MM (به وقت timezone پروژه)."""
        hour, minute = self._parse_hhmm(hhmm)

        def next_delay() -> float:
            current = now()
            target = current.replace(
                hour=hour, minute=minute, second=0, microsecond=0,
            )

            # اگر همین الان (با تلورانس ۱ ثانیه) گذشته، فردا.
            if target <= current + timedelta(seconds=1):
                target += timedelta(days=1)

            return (target.astimezone(timezone.utc) - now_utc()).total_seconds()

        return self._add(command, args_text, run_kwargs, owner, next_delay)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)

        if job is None:
            return False

        self._cancel(job)
        return True

    def cancel_owner(self, owner: object) -> int:
        """همه‌ی jobهای یک owner (معمولاً یک پلاگین) را لغو می‌کند."""
        targets = [job for job in self._jobs.values() if job.owner is owner]

        for job in targets:
            self._cancel(job)

        return len(targets)

    async def stop(self) -> None:
        """همه‌ی jobها را لغو می‌کند و منتظر پایانشان می‌ماند (موقع shutdown)."""
        current = _current_task()
        jobs = list(self._jobs.values())

        for job in jobs:
            self._cancel(job)

        tasks = [
            job.task for job in jobs
            if job.task is not None and job.task is not current
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def jobs(self) -> list[ScheduledJob]:
        return list(self._jobs.values())

    # =========================================================
    # داخلی
    # =========================================================

    @staticmethod
    def _once(compute: Callable[[], float]) -> DelayFn:
        fired = False

        def next_delay() -> Optional[float]:
            nonlocal fired

            if fired:
                return None

            fired = True
            return compute()

        return next_delay

    @staticmethod
    def _parse_hhmm(value: str) -> tuple[int, int]:
        try:
            hour, minute = (int(part) for part in value.strip().split(":"))
        except ValueError:
            raise ValueError(f"ساعت نامعتبر: '{value}' (مثال: 03:30)") from None

        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError(f"ساعت نامعتبر: '{value}' (مثال: 03:30)")

        return hour, minute

    def _add(
        self,
        command: str,
        args_text: str,
        run_kwargs: dict[str, Any],
        owner: object | None,
        next_delay: DelayFn,
    ) -> str:
        run_kwargs.setdefault("source", "scheduler")

        job = ScheduledJob(
            id=f"job-{next(self._ids)}",
            command=command,
            args_text=args_text,
            run_kwargs=run_kwargs,
            owner=owner,
        )

        job.task = asyncio.get_running_loop().create_task(
            self._loop(job, next_delay),
            name=job.id,
        )

        self._jobs[job.id] = job
        return job.id

    def _cancel(self, job: ScheduledJob) -> None:
        job.cancelled = True

        # اگر خودِ همین job (مثلاً «پلاگین آپدیت» روی پلاگینِ صاحب job) دارد
        # لغو می‌کند، task را وسط اجرا نمی‌کشیم؛ بعد از پایان اجرا متوقف می‌شود.
        if job.task is not None and job.task is not _current_task():
            job.task.cancel()

    async def _loop(self, job: ScheduledJob, next_delay: DelayFn) -> None:
        try:
            while not job.cancelled:
                delay = next_delay()

                if delay is None:
                    return

                await asyncio.sleep(max(0.0, delay))

                if job.cancelled:
                    return

                try:
                    result = await self._commands.run(
                        job.command,
                        job.args_text,
                        **job.run_kwargs,
                    )

                    if result is None:
                        print(
                            f"⚠️ Scheduler: کامند '{job.command}' "
                            f"پیدا نشد ({job.id})."
                        )

                except asyncio.CancelledError:
                    raise

                except Exception:
                    print(f"\n❌ خطا در اجرای زمان‌بندی‌شده '{job.command}' ({job.id})")
                    traceback.print_exc()

        finally:
            self._jobs.pop(job.id, None)