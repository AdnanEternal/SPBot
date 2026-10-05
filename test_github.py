import base64
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_BASE = "https://api.github.com"
TEST_PATH = "logs/stackhost_direct_github_test.txt"
CONTENT = "سلام دنیا\n"


def api_request(method, url, token, payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SPBot-StackHost-GitHub-Test",
    }

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body) if body else {}


def main():
    print("=== StackHost -> GitHub direct test ===", flush=True)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"

    if not token:
        print("❌ GITHUB_TOKEN پیدا نشد.", flush=True)
        return 1

    if not repository:
        print("❌ GITHUB_REPOSITORY پیدا نشد.", flush=True)
        return 1

    print(
        f"✅ Environment found: repository={repository}, branch={branch}",
        flush=True,
    )

    repo_api = f"{API_BASE}/repos/{repository}"
    file_api = (
        f"{repo_api}/contents/"
        f"{quote(TEST_PATH, safe='/')}"
    )

    print("⏳ در حال تست اتصال HTTPS به GitHub API...", flush=True)

    try:
        status, repo_data = api_request(
            "GET",
            repo_api,
            token,
        )

        print(
            f"✅ GitHub API connection succeeded: HTTP {status}",
            flush=True,
        )
        print(
            f"✅ Repository resolved: {repo_data.get('full_name', repository)}",
            flush=True,
        )

        current_sha = None

        try:
            file_status, file_data = api_request(
                "GET",
                f"{file_api}?ref={quote(branch, safe='')}",
                token,
            )

            if file_status == 200:
                current_sha = file_data.get("sha")
                print(
                    "ℹ️ فایل تست از قبل وجود داشت؛ به‌روزرسانی می‌شود.",
                    flush=True,
                )

        except HTTPError as exc:
            if exc.code == 404:
                print(
                    "ℹ️ فایل تست وجود ندارد؛ ساخته می‌شود.",
                    flush=True,
                )
            else:
                raise

        encoded_content = base64.b64encode(
            CONTENT.encode("utf-8")
        ).decode("ascii")

        payload = {
            "message": "test: direct StackHost GitHub connection",
            "content": encoded_content,
            "branch": branch,
        }

        if current_sha:
            payload["sha"] = current_sha

        print("⏳ در حال ارسال فایل به GitHub...", flush=True)

        write_status, write_data = api_request(
            "PUT",
            file_api,
            token,
            payload,
        )

        commit_sha = (
            write_data.get("commit", {})
            .get("sha", "unknown")
        )

        print(
            f"🎉 SUCCESS: GitHub write succeeded: HTTP {write_status}",
            flush=True,
        )
        print(
            f"✅ File: {TEST_PATH}",
            flush=True,
        )
        print(
            f"✅ Commit: {commit_sha}",
            flush=True,
        )

        return 0

    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")

        print(
            f"❌ GitHub HTTP error: {exc.code}",
            flush=True,
        )
        print(
            body,
            flush=True,
        )

        return 2

    except URLError as exc:
        print(
            f"❌ Network error while connecting to GitHub: {exc.reason}",
            flush=True,
        )
        return 3

    except TimeoutError:
        print(
            "❌ Connection to GitHub timed out.",
            flush=True,
        )
        return 4

    except Exception as exc:
        print(
            f"❌ Unexpected error: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return 5


if __name__ == "__main__":
    sys.exit(main())
