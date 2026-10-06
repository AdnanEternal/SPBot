import asyncio
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

from core.base_plugin import BasePlugin


_STATE_KEY = "_spbot_console_logger_state"
_LOCAL_LOG_PATH = Path("data/console_debug.log")


class _ConsoleCapture:
    def __init__(self, original, state):
        self._original = original
        self._state = state

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)

        # همچنان در کنسول واقعی نمایش بده
        result = self._original.write(text)

        # و همزمان داخل فایل ذخیره کن
        try:
            with self._state["lock"]:
                with self._state["path"].open(
                    "a",
                    encoding="utf-8",
                    newline="",
                ) as file:
                    file.write(text)
        except Exception:
            # لاگر نباید هیچ‌وقت باعث خرابی ربات شود.
            pass

        return result

    def flush(self):
        try:
            self._original.flush()
        finally:
            self._state["flush"]()

    def isatty(self):
        try:
            return self._original.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._original.fileno()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._original, "errors", "strict")

    @property
    def name(self):
        return getattr(self._original, "name", "<console>")

    @property
    def closed(self):
        return getattr(self._original, "closed", False)

    def writable(self):
        return True

    def readable(self):
        return False

    def __getattr__(self, name):
        return getattr(self._original, name)


def _write_local_header(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        file.write(
            "===== SPBot console log =====\n"
            f"Started: {timestamp}\n"
            "==============================\n"
        )


def _get_or_create_state():
    state = getattr(sys, _STATE_KEY, None)

    if state is not None:
        return state

    path = _LOCAL_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    # هر اجرای ربات یک لاگ تازه شروع می‌کند.
    _write_local_header(path)

    def flush():
        try:
            sys.__stdout__.flush()
        except Exception:
            pass

        try:
            sys.__stderr__.flush()
        except Exception:
            pass

    state = {
        "path": path,
        "lock": threading.RLock(),
        "original_stdout": sys.stdout,
        "original_stderr": sys.stderr,
        "flush": flush,
    }

    state["stdout"] = _ConsoleCapture(
        state["original_stdout"],
        state,
    )

    state["stderr"] = _ConsoleCapture(
        state["original_stderr"],
        state,
    )

    sys.stdout = state["stdout"]
    sys.stderr = state["stderr"]

    setattr(
        sys,
        _STATE_KEY,
        state,
    )

    return state


# خیلی مهم:
# Capture هنگام import شدن پلاگین فعال می‌شود،
# نه فقط بعد از enable شدن آن.
_STATE = _get_or_create_state()


class ConsoleLogger(BasePlugin):
    name = "Console Logger"
    version = "1.0.0"

    # قبل از پلاگین‌های معمولی فعال شود.
    startup_priority = -1000

    def __init__(
        self,
        client,
        command_manager,
        db,
        event_bus,
    ):
        super().__init__(
            client,
            command_manager,
            db,
            event_bus,
        )

        from plugins.system_plugin.github_manager.manager import (
            GitHubManager,
        )

        self._github = GitHubManager()

        self._sync_task = None
        self._stop_event = asyncio.Event()
        self._sync_lock = asyncio.Lock()

        self._remote_path = self.config.get(
            "GITHUB_CONSOLE_LOG_PATH",
            "logs/console.log",
        )

        try:
            self._interval = max(
                2,
                float(
                    self.config.get(
                        "GITHUB_CONSOLE_LOG_INTERVAL",
                        "5",
                    )
                ),
            )
        except (TypeError, ValueError):
            self._interval = 5.0

    async def on_enable(self):
        self._stop_event.clear()

        self._sync_task = asyncio.create_task(
            self._sync_loop(),
            name="spbot-console-log-sync",
        )

    async def on_disable(self):
        self._stop_event.set()

        task = self._sync_task
        self._sync_task = None

        if task is not None:
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                self._safe_console(
                    "⚠️ Console Logger sync task "
                    "unexpectedly failed.\n"
                )

        # آخرین آپلود قبل از خاموش شدن
        await self._sync_once()

    async def _sync_loop(self):
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )

                break

            except asyncio.TimeoutError:
                await self._sync_once()

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                self._safe_console(
                    "⚠️ Console Logger loop error: "
                    f"{type(exc).__name__}: {exc}\n"
                )

    async def _sync_once(self):
        async with self._sync_lock:
            upload_path = None

            try:
                upload_path = await self._snapshot_log()

                await self._github.upload_file(
                    local_path=str(upload_path),
                    remote_path=self._remote_path,
                    commit_message="debug: update console log",
                )

            except Exception as exc:
                # عمداً print استفاده نمی‌کنیم،
                # چون خطای GitHub خودش دوباره وارد لاگ می‌شود.
                self._safe_console(
                    "⚠️ Console Logger upload failed: "
                    f"{type(exc).__name__}: {exc}\n"
                )

            finally:
                if upload_path is not None:
                    try:
                        upload_path.unlink(
                            missing_ok=True
                        )
                    except Exception:
                        pass

    async def _snapshot_log(self) -> Path:
        source = _STATE["path"]

        snapshot = source.with_name(
            "console_debug_upload.tmp"
        )

        def copy_log():
            with _STATE["lock"]:
                shutil.copyfile(
                    source,
                    snapshot,
                )

        await asyncio.to_thread(copy_log)

        return snapshot

    @staticmethod
    def _safe_console(text: str):
        try:
            sys.__stderr__.write(text)
            sys.__stderr__.flush()
        except Exception:
            pass