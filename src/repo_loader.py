from __future__ import annotations

import re
import shutil
import subprocess
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


class RepoLoadError(RuntimeError):
    """Raised when a repository URL cannot be parsed or cloned."""


@dataclass
class RepoReference:
    owner: str
    name: str
    safe_name: str
    clone_url: str
    web_url: str


@dataclass
class RepoLoadResult:
    owner: str
    name: str
    safe_name: str
    clone_url: str
    web_url: str
    local_path: str
    from_cache: bool
    refreshed: bool
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


_GITHUB_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_github_url(url: str) -> RepoReference:
    """Parse HTTPS or SSH GitHub repository URLs into a normalized reference."""
    raw_url = (url or "").strip()
    if not raw_url:
        raise RepoLoadError("请输入 GitHub 仓库 URL。")

    path = ""
    if raw_url.startswith("git@github.com:"):
        path = raw_url.split(":", 1)[1]
    else:
        parsed = urlparse(raw_url)
        host = parsed.netloc.lower()
        if host not in {"github.com", "www.github.com"}:
            raise RepoLoadError("目前仅支持 github.com 仓库地址。")
        path = parsed.path.lstrip("/")

    path = path.removesuffix(".git").strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        raise RepoLoadError("URL 中没有识别到 owner/repo，请检查仓库地址。")

    owner, repo_name = parts[0], parts[1]
    if not _GITHUB_NAME_RE.match(owner) or not _GITHUB_NAME_RE.match(repo_name):
        raise RepoLoadError("仓库 owner 或 repo 名称包含不支持的字符。")

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{owner}_{repo_name}")
    return RepoReference(
        owner=owner,
        name=repo_name,
        safe_name=safe_name,
        clone_url=f"https://github.com/{owner}/{repo_name}.git",
        web_url=f"https://github.com/{owner}/{repo_name}",
    )


def clone_or_use_cache(url: str, base_dir: Path, refresh: bool = False) -> RepoLoadResult:
    """Clone a GitHub repository, or reuse the existing local cache."""
    reference = parse_github_url(url)
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_path = base_dir / reference.safe_name

    if repo_path.exists() and not refresh:
        return RepoLoadResult(
            owner=reference.owner,
            name=reference.name,
            safe_name=reference.safe_name,
            clone_url=reference.clone_url,
            web_url=reference.web_url,
            local_path=str(repo_path),
            from_cache=True,
            refreshed=False,
            message="已使用本地缓存仓库进行分析。",
        )

    if repo_path.exists() and refresh:
        _remove_cached_repo(repo_path, base_dir)

    try:
        completed = subprocess.run(
            ["git", "clone", "--depth", "1", reference.clone_url, str(repo_path)],
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RepoLoadError("未检测到 git 命令，请先安装 Git 并确认它在 PATH 中。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RepoLoadError("克隆超时，请检查网络连接或稍后重试。") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        friendly = "仓库克隆失败，请确认仓库公开可访问、URL 正确且网络可用。"
        if detail:
            friendly = f"{friendly}\n\nGit 输出：{detail[-800:]}"
        raise RepoLoadError(friendly)

    return RepoLoadResult(
        owner=reference.owner,
        name=reference.name,
        safe_name=reference.safe_name,
        clone_url=reference.clone_url,
        web_url=reference.web_url,
        local_path=str(repo_path),
        from_cache=False,
        refreshed=refresh,
        message="仓库克隆完成。",
    )


def _remove_cached_repo(repo_path: Path, base_dir: Path) -> None:
    base = base_dir.resolve()
    target = repo_path.resolve()
    if target == base or base not in target.parents:
        raise RepoLoadError("缓存目录校验失败，已取消删除操作。")
    try:
        shutil.rmtree(target, onerror=_handle_remove_readonly)
    except PermissionError as exc:
        raise RepoLoadError(
            "无法删除本地仓库缓存，可能是 .git 对象文件被 Git、编辑器、杀毒软件或系统索引占用，"
            "也可能存在只读文件。请关闭正在使用该仓库的程序后重试；如果只是想重新查看分析结果，"
            "也可以取消“重新克隆”并直接使用缓存。"
        ) from exc
    except OSError as exc:
        raise RepoLoadError(f"删除本地仓库缓存失败：{exc}") from exc


def _handle_remove_readonly(func, path: str, exc_info) -> None:
    """Retry removing read-only files left by git packs on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except PermissionError:
        raise
