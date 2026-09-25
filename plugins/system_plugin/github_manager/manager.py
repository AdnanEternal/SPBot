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

        headers = {
            **self.headers,
            "Accept": "application/vnd.github.raw+json",
        }

        timeout = aiohttp.ClientTimeout(total=120)

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
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

                data = await response.read()

        with open(local_path, "wb") as file:
            file.write(data)


    async def rotate_database_backup(
    self,
    local_path: str,
    latest_path: str,
    archive_path: str,
    commit_message: str,
) -> None:
        """
        بکاپ جدید را به latest_path می‌فرستد و latest قبلی را
        در همان commit به archive_path منتقل می‌کند.

        مثال:
            backups/latest.db
            ->
            backups/database_2026-09-25_17-38-00.db

        سپس فایل جدید در:
            backups/latest.db
        قرار می‌گیرد.

        این عملیات در یک commit انجام می‌شود.
        """

        

        with open(
            local_path,
            "rb",
        ) as file:
            new_content = base64.b64encode(
                file.read()
            ).decode("utf-8")

        base_url = (
            f"{self.BASE_URL}/repos/"
            f"{self.repository}"
        )

        async with aiohttp.ClientSession(
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(
                total=120
            ),
        ) as session:

            # -------------------------------------------------
            # 1. بررسی latest فعلی
            # -------------------------------------------------

            latest_url = (
                f"{base_url}/contents/"
                f"{latest_path}"
            )

            old_latest_sha = None

            async with session.get(
                latest_url,
                params={"ref": self.branch},
                headers={
                    **self.headers,
                    "Accept": (
                        "application/vnd.github+json"
                    ),
                },
            ) as response:

                if response.status == 200:
                    data = await response.json()

                    old_latest_sha = data.get(
                        "sha"
                    )

                elif response.status != 404:
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to inspect current "
                        f"database backup: "
                        f"{response.status} - {text}"
                    )

            # -------------------------------------------------
            # 2. گرفتن HEAD branch
            # -------------------------------------------------

            ref_url = (
                f"{base_url}/git/ref/"
                f"heads/{self.branch}"
            )

            async with session.get(
                ref_url
            ) as response:

                if response.status != 200:
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to get GitHub branch "
                        f"reference: "
                        f"{response.status} - {text}"
                    )

                ref_data = await response.json()

            parent_commit_sha = (
                ref_data["object"]["sha"]
            )

            # -------------------------------------------------
            # 3. گرفتن tree فعلی
            # -------------------------------------------------

            commit_url = (
                f"{base_url}/git/commits/"
                f"{parent_commit_sha}"
            )

            async with session.get(
                commit_url
            ) as response:

                if response.status != 200:
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to get current commit: "
                        f"{response.status} - {text}"
                    )

                commit_data = await response.json()

            base_tree_sha = (
                commit_data["tree"]["sha"]
            )

            # -------------------------------------------------
            # 4. ساخت blob برای بکاپ جدید
            # -------------------------------------------------

            blob_url = (
                f"{base_url}/git/blobs"
            )

            async with session.post(
                blob_url,
                json={
                    "content": new_content,
                    "encoding": "base64",
                },
            ) as response:

                if response.status not in (
                    201,
                ):
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to create database "
                        f"backup blob: "
                        f"{response.status} - {text}"
                    )

                blob_data = await response.json()

            new_blob_sha = blob_data["sha"]

            # -------------------------------------------------
            # 5. ساخت tree جدید
            #
            # latest جدید:
            #   latest_path -> new blob
            #
            # latest قبلی:
            #   archive_path -> old blob
            # -------------------------------------------------

            tree_entries = [
                {
                    "path": latest_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": new_blob_sha,
                }
            ]

            if old_latest_sha:
                tree_entries.append(
                    {
                        "path": archive_path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": old_latest_sha,
                    }
                )

            tree_url = (
                f"{base_url}/git/trees"
            )

            async with session.post(
                tree_url,
                json={
                    "base_tree": base_tree_sha,
                    "tree": tree_entries,
                },
            ) as response:

                if response.status != 201:
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to create backup "
                        f"tree: "
                        f"{response.status} - {text}"
                    )

                tree_data = await response.json()

            new_tree_sha = tree_data["sha"]

            # -------------------------------------------------
            # 6. ساخت commit
            # -------------------------------------------------

            create_commit_url = (
                f"{base_url}/git/commits"
            )

            async with session.post(
                create_commit_url,
                json={
                    "message": commit_message,
                    "tree": new_tree_sha,
                    "parents": [
                        parent_commit_sha
                    ],
                },
            ) as response:

                if response.status != 201:
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to create backup "
                        f"commit: "
                        f"{response.status} - {text}"
                    )

                new_commit_data = (
                    await response.json()
                )

            new_commit_sha = (
                new_commit_data["sha"]
            )

            # -------------------------------------------------
            # 7. انتقال branch به commit جدید
            # -------------------------------------------------

            update_ref_url = (
                f"{base_url}/git/refs/heads/"
                f"{self.branch}"
            )

            async with session.patch(
                update_ref_url,
                json={
                    "sha": new_commit_sha,
                    "force": False,
                },
            ) as response:

                if response.status != 200:
                    text = await response.text()

                    raise RuntimeError(
                        "Failed to update GitHub "
                        f"branch: "
                        f"{response.status} - {text}"
                    )