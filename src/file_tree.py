from __future__ import annotations

import os
from collections import Counter, defaultdict
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "venv",
    ".venv",
    "env",
    "ENV",
    "node_modules",
    "site-packages",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    "coverage",
}

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".swift",
    ".scala",
    ".sh",
    ".ps1",
    ".sql",
    ".html",
    ".css",
    ".scss",
}

DOCUMENT_EXTENSIONS = {".md", ".rst", ".txt", ".adoc", ".pdf"}
CONFIG_EXTENSIONS = {".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".json", ".xml"}
ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".mp4",
    ".mp3",
    ".wav",
    ".ttf",
    ".woff",
    ".woff2",
}
CONFIG_FILENAMES = {
    ".gitignore",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pom.xml",
    "build.gradle",
    "gradlew",
    "makefile",
}

EXTENSION_LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".scala": "Scala",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".ps1": "PowerShell",
}


def analyze_file_tree(repo_path: Path) -> dict:
    """Analyze repository structure without reading full source code content."""
    repo_path = Path(repo_path)
    extension_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    largest_files: list[dict] = []
    top_dirs = defaultdict(lambda: {"files": 0, "size_bytes": 0})
    language_line_counts: Counter[str] = Counter()
    total_files = 0
    total_dirs = 0
    total_size = 0
    total_code_lines = 0

    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        total_dirs += len(dirnames)

        for filename in filenames:
            path = Path(current_root) / filename
            if _is_ignored_path(path, repo_path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue

            rel_path = path.relative_to(repo_path).as_posix()
            suffix = path.suffix.lower() or "[no extension]"
            category = classify_file(path)

            total_files += 1
            total_size += size
            extension_counts[suffix] += 1
            category_counts[category] += 1
            if category == "code":
                line_count = _count_lines(path)
                total_code_lines += line_count
                language = EXTENSION_LANGUAGE_MAP.get(path.suffix.lower(), "Other")
                language_line_counts[language] += line_count
            largest_files.append(
                {
                    "path": rel_path,
                    "size_bytes": size,
                    "size_kb": round(size / 1024, 2),
                    "category": category,
                }
            )

            top_key = Path(rel_path).parts[0] if len(Path(rel_path).parts) > 1 else "."
            top_dirs[top_key]["files"] += 1
            top_dirs[top_key]["size_bytes"] += size

    largest_files = sorted(largest_files, key=lambda item: item["size_bytes"], reverse=True)[:10]
    directory_summary = [
        {
            "directory": directory,
            "files": values["files"],
            "size_kb": round(values["size_bytes"] / 1024, 2),
        }
        for directory, values in sorted(
            top_dirs.items(), key=lambda item: item[1]["size_bytes"], reverse=True
        )
    ][:12]

    ratios = {
        category: round((count / total_files) * 100, 2) if total_files else 0
        for category, count in category_counts.items()
    }

    return {
        "total_files": total_files,
        "total_dirs": total_dirs,
        "total_size_kb": round(total_size / 1024, 2),
        "total_code_lines": total_code_lines,
        "language_line_counts": dict(language_line_counts.most_common()),
        "extension_counts": dict(extension_counts.most_common()),
        "category_counts": dict(category_counts),
        "category_ratios": ratios,
        "largest_files": largest_files,
        "directory_summary": directory_summary,
        "tree": build_tree(repo_path, max_depth=3, max_entries_per_dir=18),
    }


def classify_file(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in CONFIG_FILENAMES or suffix in CONFIG_EXTENSIONS:
        return "config"
    if suffix in DOCUMENT_EXTENSIONS or name.startswith("readme") or name == "license":
        return "documentation"
    if suffix in CODE_EXTENSIONS:
        return "code"
    if suffix in ASSET_EXTENSIONS:
        return "asset"
    return "other"


def build_tree(repo_path: Path, max_depth: int = 3, max_entries_per_dir: int = 18) -> str:
    repo_path = Path(repo_path)
    lines = [f"{repo_path.name}/"]

    def walk(directory: Path, prefix: str, depth: int) -> None:
        if depth >= max_depth:
            return
        try:
            entries = [
                item
                for item in directory.iterdir()
                if not _is_ignored_path(item, repo_path) and item.name not in IGNORED_DIRS
            ]
        except OSError:
            return

        entries = sorted(entries, key=lambda item: (not item.is_dir(), item.name.lower()))
        visible_entries = entries[:max_entries_per_dir]
        hidden_count = max(0, len(entries) - len(visible_entries))

        for index, item in enumerate(visible_entries):
            is_last = index == len(visible_entries) - 1 and hidden_count == 0
            connector = "`-- " if is_last else "|-- "
            suffix = "/" if item.is_dir() else ""
            lines.append(f"{prefix}{connector}{item.name}{suffix}")
            if item.is_dir():
                child_prefix = f"{prefix}{'    ' if is_last else '|   '}"
                walk(item, child_prefix, depth + 1)

        if hidden_count:
            lines.append(f"{prefix}`-- ... {hidden_count} more")

    walk(repo_path, "", 0)
    return "\n".join(lines)


def _is_ignored_path(path: Path, repo_path: Path) -> bool:
    try:
        relative_parts = path.relative_to(repo_path).parts
    except ValueError:
        return True
    return any(part in IGNORED_DIRS for part in relative_parts)


def _count_lines(path: Path) -> int:
    try:
        if path.stat().st_size > 1_500_000:
            return 0
        return path.read_text(encoding="utf-8", errors="ignore").count("\n") + 1
    except OSError:
        return 0
