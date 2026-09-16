import base64

import aiohttp

from config import config


class GitHubManager:
    BASE_URL = "https://api.github.com"

    def __init__(self):
        self.token = config.get("GITHUB_TOKEN")
        self.repository = config.get("GITHUB_REPOSITORY")
        self.branch = config.get("GITHUB_BRANCH", "main")

        if not self.token:
            raise ValueError("GITHUB_TOKEN is not configured")

        if not self.repository:
            raise ValueError("GITHUB_REPOSITORY is not configured")

        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def check_connection(self) -> bool:
        url = f"{self.BASE_URL}/repos/{self.repository}"

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return True

                text = await response.text()
                raise RuntimeError(
                    f"GitHub connection failed: "
                    f"{response.status} - {text}"
                )

    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        commit_message: str,
    ) -> None:
        url = (
            f"{self.BASE_URL}/repos/"
            f"{self.repository}/contents/{remote_path}"
        )

        with open(local_path, "rb") as file:
            content = base64.b64encode(file.read()).decode("utf-8")

        async with aiohttp.ClientSession(headers=self.headers) as session:
            sha = None

            # ببینیم فایل از قبل وجود دارد یا نه
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
                        f"Failed to check remote file: "
                        f"{response.status} - {text}"
                    )

            payload = {
                "message": commit_message,
                "content": content,
                "branch": self.branch,
            }

            if sha:
                payload["sha"] = sha

            async with session.put(url, json=payload) as response:
                if response.status not in (200, 201):
                    text = await response.text()
                    raise RuntimeError(
                        f"GitHub upload failed: "
                        f"{response.status} - {text}"
                    )