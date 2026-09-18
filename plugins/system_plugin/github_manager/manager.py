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

    async def download_file(
        self,
        remote_path: str,
        local_path: str,
    ) -> None:
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
                        "GitHub download failed: "
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

        with open(
            local_path,
            "wb",
        ) as file:
            file.write(decoded)