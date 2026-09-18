import base64

import aiohttp

from config import config


class GitHubManager:
    BASE_URL = "https://api.github.com"
    REQUEST_TIMEOUT = 30

    def __init__(self):
        self.token = config.get("GITHUB_TOKEN")
        self.repository = config.get(
            "GITHUB_REPOSITORY"
        )
        self.branch = config.get(
            "GITHUB_BRANCH",
            "main",
        )

        if not self.token:
            raise ValueError(
                "GITHUB_TOKEN is not configured"
            )

        if not self.repository:
            raise ValueError(
                "GITHUB_REPOSITORY is not configured"
            )

        self.headers = {
            "Accept": (
                "application/vnd.github+json"
            ),
            "Authorization": (
                f"Bearer {self.token}"
            ),
            "X-GitHub-Api-Version": (
                "2022-11-28"
            ),
        }

    def _timeout(self):
        return aiohttp.ClientTimeout(
            total=self.REQUEST_TIMEOUT
        )

    async def download_directory(
        self,
        remote_path: str,
        local_path: str,
    ) -> None:
        from pathlib import Path

        local_dir = Path(local_path)
        local_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        entries = await self.list_directory(
            remote_path
        )

        for entry in entries:
            name = entry.get("name")
            entry_type = entry.get("type")

            if not name:
                continue

            child_remote_path = (
                f"{remote_path.rstrip('/')}/{name}"
            )

            child_local_path = (
                local_dir / name
            )

            if entry_type == "dir":
                await self.download_directory(
                    child_remote_path,
                    str(child_local_path),
                )

            elif entry_type == "file":
                await self.download_file(
                    remote_path=child_remote_path,
                    local_path=str(
                        child_local_path
                    ),
                )

    async def check_connection(self) -> bool:
        url = (
            f"{self.BASE_URL}/repos/"
            f"{self.repository}"
        )

        async with aiohttp.ClientSession(
            headers=self.headers,
            timeout=self._timeout(),
        ) as session:
            async with session.get(
                url
            ) as response:

                if response.status == 200:
                    return True

                text = await response.text()

                raise RuntimeError(
                    "GitHub connection failed: "
                    f"{response.status} - {text}"
                )

    async def list_directory(
        self,
        remote_path: str,
    ) -> list[dict]:
        url = (
            f"{self.BASE_URL}/repos/"
            f"{self.repository}/contents/"
            f"{remote_path}"
        )

        async with aiohttp.ClientSession(
            headers=self.headers,
            timeout=self._timeout(),
        ) as session:
            async with session.get(
                url,
                params={"ref": self.branch},
            ) as response:

                if response.status != 200:
                    text = await response.text()

                    raise RuntimeError(
                        "GitHub directory listing failed: "
                        f"{response.status} - {text}"
                    )

                data = await response.json()

        if not isinstance(data, list):
            raise RuntimeError(
                f"GitHub path '{remote_path}' "
                "is not a directory"
            )

        return data

    async def read_text_file(
        self,
        remote_path: str,
    ) -> str:
        url = (
            f"{self.BASE_URL}/repos/"
            f"{self.repository}/contents/"
            f"{remote_path}"
        )

        async with aiohttp.ClientSession(
            headers=self.headers,
            timeout=self._timeout(),
        ) as session:
            async with session.get(
                url,
                params={"ref": self.branch},
            ) as response:

                if response.status != 200:
                    text = await response.text()

                    raise RuntimeError(
                        "GitHub file read failed: "
                        f"{response.status} - {text}"
                    )

                data = await response.json()

        if data.get("encoding") != "base64":
            raise RuntimeError(
                "GitHub returned an unsupported "
                "file encoding"
            )

        content = data.get("content")

        if not content:
            raise RuntimeError(
                "GitHub returned an empty file"
            )

        try:
            decoded = base64.b64decode(
                content.replace("\n", "")
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to decode GitHub file: {e}"
            ) from e

        return decoded.decode("utf-8")

    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        commit_message: str,
    ) -> None:
        url = (
            f"{self.BASE_URL}/repos/"
            f"{self.repository}/contents/"
            f"{remote_path}"
        )

        with open(
            local_path,
            "rb",
        ) as file:
            content = base64.b64encode(
                file.read()
            ).decode("utf-8")

        async with aiohttp.ClientSession(
            headers=self.headers,
            timeout=self._timeout(),
        ) as session:

            sha = None

            async with session.get(
                url,
                params={"ref": self.branch},
            ) as response:

                if response.status == 200:
                    data = await response.json()
                    sha = data["sha"]

                elif response.status != 404:
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to check remote file: "
                        f"{response.status} - {text}"
                    )

            payload = {
                "message": commit_message,
                "content": content,
                "branch": self.branch,
            }

            if sha:
                payload["sha"] = sha

            async with session.put(
                url,
                json=payload,
            ) as response:

                if response.status not in (
                    200,
                    201,
                ):
                    text = await response.text()

                    raise RuntimeError(
                        "GitHub upload failed: "
                        f"{response.status} - {text}"
                    )

"""
وضعیت کوتاه‌مدت و درجا (in-memory، نه دیتابیس) برای تشخیص فلاد و
پیام تکراری. عمداً تو دیتابیس ذخیره نمی‌شه چون عمرش کوتاهه و با
ری‌استارت ربات از نو شروع شدنش مشکلی نداره.
"""

import time
from collections import defaultdict, deque
from typing import Optional


class SpamTracker:
    CLEANUP_EVERY = 500   # هر چند پیام یه بار پاک‌سازی انجام بشه
    STALE_SECONDS = 600   # کاربری که ۱۰ دقیقه پیام نداده از حافظه پاک می‌شه

    def __init__(self) -> None:
        self._messages: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=100))
        self._last_text: dict[tuple[int, int], tuple[str, int]] = {}
        self._register_calls = 0

    def register(self, group_id: int, user_id: int, message_id: int, text: str) -> int:
        """
        پیام رو ثبت می‌کنه و تعداد تکرار پشت‌سرهمِ عین همین متن رو
        برمی‌گردونه (پیام غیرمتنی/خالی هیچ‌وقت «تکراری» حساب نمی‌شه).
        """
        self._register_calls += 1
        if self._register_calls % self.CLEANUP_EVERY == 0:
            self._cleanup()

        key = (group_id, user_id)
        self._messages[key].append((time.time(), message_id))

        last_text, repeat_count = self._last_text.get(key, ("", 0))
        repeat_count = repeat_count + 1 if text and text == last_text else 1
        self._last_text[key] = (text, repeat_count)

        return repeat_count

    def clear_user(self, group_id: int, user_id: int) -> None:
        key = (group_id, user_id)
        self._messages.pop(key, None)
        self._last_text.pop(key, None)

    def _cleanup(self) -> None:
        cutoff = time.time() - self.STALE_SECONDS
        stale = [
            key
            for key, messages in self._messages.items()
            if not messages or messages[-1][0] < cutoff
        ]
        for key in stale:
            self._messages.pop(key, None)
            self._last_text.pop(key, None)

    def count_in_window(self, group_id: int, user_id: int, seconds: int) -> int:
        cutoff = time.time() - seconds
        messages = self._messages.get((group_id, user_id), ())
        return sum(1 for ts, _ in messages if ts >= cutoff)

    def ids_in_window(self, group_id: int, user_id: int, seconds: int) -> list[int]:
        cutoff = time.time() - seconds
        messages = self._messages.get((group_id, user_id), ())
        return [mid for ts, mid in messages if ts >= cutoff]


class AdminCache:
    """
    is_chat_admin یه API call نسبتاً گرون می‌زنه؛ نتیجه رو چند دقیقه
    cache می‌کنیم که رو گروه‌های پرترافیک هر پیام یه API call نزنیم.
    """

    TTL_SECONDS = 300
    MAX_ENTRIES = 5000

    def __init__(self) -> None:
        self._cache: dict[tuple[int, int], tuple[bool, float]] = {}

    def get(self, group_id: int, user_id: int) -> Optional[bool]:
        entry = self._cache.get((group_id, user_id))
        if entry is None:
            return None

        is_admin, cached_at = entry
        if time.time() - cached_at > self.TTL_SECONDS:
            return None
        return is_admin

    def set(self, group_id: int, user_id: int, is_admin: bool) -> None:
        if len(self._cache) >= self.MAX_ENTRIES:
            now = time.time()
            self._cache = {
                key: value
                for key, value in self._cache.items()
                if now - value[1] <= self.TTL_SECONDS
            }

        self._cache[(group_id, user_id)] = (is_admin, time.time())