from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from .analysis_models import RepositoryContext
from .file_tree import IGNORED_DIRS


DEPENDENCY_FILENAMES = {
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "Cargo.toml",
}
CONFIG_SUFFIXES = {".toml", ".yaml", ".yml", ".ini", ".cfg", ".json"}
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".php", ".rb", ".cs"}
ENTRY_CANDIDATES = {
    "app.py",
    "main.py",
    "manage.py",
    "server.py",
    "wsgi.py",
    "asgi.py",
    "index.js",
    "src/main.ts",
    "src/main.tsx",
    "src/App.jsx",
    "src/App.tsx",
}


def build_repository_context(repo_info: dict[str, Any], github_api: dict[str, Any] | None = None) -> RepositoryContext:
    repo_path = Path(repo_info["local_path"])
    readme_text = _readme_text(repo_path) or ((github_api or {}).get("readme") or {}).get("excerpt", "")
    dependency_files: dict[str, str] = {}
    config_files: list[str] = []
    test_files: list[str] = []
    deploy_files: list[str] = []
    source_files: list[Path] = []

    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        current_path = Path(current_root)
        for filename in filenames:
            path = current_path / filename
            rel_path = path.relative_to(repo_path).as_posix()
            lower_name = filename.lower()
            if filename in DEPENDENCY_FILENAMES:
                dependency_files[rel_path] = _read_limited_text(path, 20_000)
            if _is_config_file(path):
                config_files.append(rel_path)
            if _is_test_file(path, current_path):
                test_files.append(rel_path)
            if _is_deploy_file(rel_path, filename):
                deploy_files.append(rel_path)
            if path.suffix.lower() in SOURCE_SUFFIXES:
                source_files.append(path)

    source_samples = _source_samples(repo_path, source_files)
    import_summary = _import_summary(repo_path, source_files)

    return RepositoryContext(
        repo_name=repo_info.get("name", repo_path.name),
        owner=repo_info.get("owner", ""),
        url=repo_info.get("web_url") or repo_info.get("clone_url") or "",
        local_path=str(repo_path),
        readme_text=readme_text[:40_000],
        dependency_files=dependency_files,
        source_samples=source_samples,
        test_files=sorted(test_files)[:300],
        config_files=sorted(config_files)[:300],
        deploy_files=sorted(deploy_files)[:200],
        import_summary=import_summary,
        possible_entry_files=_possible_entry_files(repo_path),
    )


def _readme_text(repo_path: Path) -> str:
    for name in ("README.md", "README.rst", "README.txt", "readme.md"):
        path = repo_path / name
        if path.exists():
            return _read_limited_text(path, 60_000)
    return ""


def _read_limited_text(path: Path, limit: int) -> str:
    try:
        if path.stat().st_size > limit * 8:
            return path.read_text(encoding="utf-8", errors="ignore")[:limit]
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def _is_config_file(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() in CONFIG_SUFFIXES or name in {".gitignore", "dockerfile", ".env.example"}


def _is_test_file(path: Path, current_path: Path) -> bool:
    lower_name = path.name.lower()
    parts = {part.lower() for part in current_path.parts}
    return "tests" in parts or "test" in parts or lower_name.startswith("test_") or lower_name.endswith("_test.py")


def _is_deploy_file(rel_path: str, filename: str) -> bool:
    lower = rel_path.lower()
    name = filename.lower()
    return (
        name in {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "vercel.json", "render.yaml"}
        or lower.startswith(".github/workflows/")
        or lower.endswith(".service")
        or lower.endswith("deploy.yml")
        or lower.endswith("deploy.yaml")
    )


def _source_samples(repo_path: Path, source_files: list[Path]) -> list[dict[str, Any]]:
    samples = []
    priority = sorted(source_files, key=lambda path: (0 if path.name in {"app.py", "main.py"} else 1, len(path.parts), path.name))
    for path in priority[:25]:
        text = _read_limited_text(path, 8_000)
        if not text:
            continue
        samples.append(
            {
                "path": path.relative_to(repo_path).as_posix(),
                "lines": text.count("\n") + 1,
                "excerpt": text[:1200],
            }
        )
    return samples


def _import_summary(repo_path: Path, source_files: list[Path]) -> dict[str, Any]:
    imports: dict[str, int] = {}
    files_with_imports: list[str] = []
    for path in [item for item in source_files if item.suffix.lower() == ".py"][:120]:
        text = _read_limited_text(path, 80_000)
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        file_has_import = False
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                imports[name] = imports.get(name, 0) + 1
                file_has_import = True
        if file_has_import:
            files_with_imports.append(path.relative_to(repo_path).as_posix())
    return {
        "top_imports": [
            {"name": name, "count": count}
            for name, count in sorted(imports.items(), key=lambda item: item[1], reverse=True)[:30]
        ],
        "files_scanned": len(files_with_imports),
    }


def _possible_entry_files(repo_path: Path) -> list[str]:
    entries = []
    for candidate in ENTRY_CANDIDATES:
        if (repo_path / candidate).exists():
            entries.append(candidate)
    return entries
