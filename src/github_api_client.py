from __future__ import annotations

import base64
import os
from datetime import datetime
from typing import Any

import requests

from .repo_loader import RepoLoadError, parse_github_url


GITHUB_API_ROOT = "https://api.github.com"


def fetch_github_api_snapshot(repo_url: str, timeout: int = 10) -> dict[str, Any]:
    """Fetch public GitHub metadata, tree entries, and README through GitHub API.

    The app still clones the repository for deterministic local analysis. This
    snapshot satisfies the API-oriented view and gives the dashboard repository
    metadata even before reading local files.
    """
    try:
        reference = parse_github_url(repo_url)
    except RepoLoadError as exc:
        return _unavailable(str(exc))

    headers = _github_headers()
    repo_api_url = f"{GITHUB_API_ROOT}/repos/{reference.owner}/{reference.name}"

    try:
        repo_data = _get_json(repo_api_url, headers, timeout, "获取仓库信息")
    except Exception as exc:
        return _unavailable(str(exc))

    default_branch = repo_data.get("default_branch") or "main"
    tree = _fetch_tree(reference.owner, reference.name, default_branch, headers, timeout)
    readme = _fetch_readme(reference.owner, reference.name, headers, timeout)

    return {
        "available": True,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": {
            "full_name": repo_data.get("full_name"),
            "description": repo_data.get("description") or "",
            "homepage": repo_data.get("homepage") or "",
            "default_branch": default_branch,
            "language": repo_data.get("language") or "Unknown",
            "stars": repo_data.get("stargazers_count", 0),
            "forks": repo_data.get("forks_count", 0),
            "open_issues": repo_data.get("open_issues_count", 0),
            "size_kb": repo_data.get("size", 0),
            "created_at": repo_data.get("created_at"),
            "updated_at": repo_data.get("updated_at"),
            "license": (repo_data.get("license") or {}).get("spdx_id") or "None",
            "topics": repo_data.get("topics") or [],
            "html_url": repo_data.get("html_url"),
        },
        "tree": tree,
        "readme": readme,
        "error": None,
    }


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-repo-analyzer-course-design",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str, headers: dict[str, str], timeout: int, action: str) -> dict[str, Any]:
    response = requests.get(url, headers=headers, timeout=timeout)
    if response.status_code == 403 and _is_rate_limited(response):
        raise RuntimeError(_rate_limit_message(response, action))
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f"GitHub API {action}失败：{exc}") from exc
    return response.json()


def _is_rate_limited(response: requests.Response) -> bool:
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    try:
        message = (response.json().get("message") or "").lower()
    except Exception:
        message = response.text.lower()
    return "rate limit" in message or "api rate limit exceeded" in message


def _rate_limit_message(response: requests.Response, action: str) -> str:
    reset_hint = ""
    reset_at = response.headers.get("X-RateLimit-Reset")
    if reset_at and reset_at.isdigit():
        reset_hint = f"，预计 {datetime.fromtimestamp(int(reset_at)).strftime('%H:%M:%S')} 后恢复"
    return (
        f"GitHub API {action}触发限流{reset_hint}。"
        "系统已降级为 git clone + 本地静态分析；"
        "如需更高限额，请设置 GITHUB_TOKEN 或 GH_TOKEN 后重启 Streamlit。"
    )


def _fetch_tree(
    owner: str,
    repo: str,
    branch: str,
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    url = f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    try:
        payload = _get_json(url, headers, timeout, "获取文件树")
    except Exception as exc:
        return {"available": False, "error": str(exc), "items": []}

    items = payload.get("tree") or []
    files = [item for item in items if item.get("type") == "blob"]
    dirs = [item for item in items if item.get("type") == "tree"]
    return {
        "available": True,
        "truncated": bool(payload.get("truncated")),
        "total_items": len(items),
        "file_count": len(files),
        "dir_count": len(dirs),
        "sample_paths": [item.get("path") for item in items[:120] if item.get("path")],
    }


def _fetch_readme(owner: str, repo: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    url = f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/readme"
    try:
        payload = _get_json(url, headers, timeout, "获取 README")
    except Exception as exc:
        return {"available": False, "error": str(exc), "path": None, "excerpt": ""}

    raw_content = payload.get("content") or ""
    try:
        text = base64.b64decode(raw_content).decode("utf-8", errors="ignore")
    except Exception:
        text = ""
    excerpt = text[:4000]
    return {
        "available": True,
        "path": payload.get("path"),
        "size": payload.get("size", 0),
        "excerpt": excerpt,
    }


def _unavailable(error: str) -> dict[str, Any]:
    return {
        "available": False,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": {},
        "tree": {"available": False, "items": []},
        "readme": {"available": False, "excerpt": ""},
        "error": error,
    }
