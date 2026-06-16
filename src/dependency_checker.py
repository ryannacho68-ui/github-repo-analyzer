from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PINNED_PATTERNS = [
    re.compile(r"^[A-Za-z0-9_.-]+==[^=].+"),
    re.compile(r'^[A-Za-z0-9_.@/-]+@?\s*"?\d+\.\d+'),
]


def check_dependency_health(repo_path: Path, tech_stack: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    dependencies = tech_stack.get("dependencies") or {}
    dependency_versions = tech_stack.get("dependency_versions") or {}
    dependency_files = (context or {}).get("dependency_files") or {}

    flat_deps = []
    for group, values in dependencies.items():
        for value in values:
            flat_deps.append((group, str(value)))

    normalized = [name.lower() for _, name in flat_deps]
    duplicates = sorted({name for name in normalized if normalized.count(name) > 1})

    version_specs = []
    for group, values in dependency_versions.items():
        for value in values:
            version_specs.append((group, str(value)))

    pinned_count = sum(1 for _, spec in version_specs if _is_pinned(spec))
    unpinned_count = max(0, len(flat_deps) - pinned_count)
    score = 10.0
    suggestions = []

    if not dependency_files:
        score -= 2
        suggestions.append("未检测到标准依赖文件，建议补充 requirements.txt、pyproject.toml、package.json 或同类文件。")
    if len(flat_deps) > 80:
        score -= 1.5
        suggestions.append("依赖数量较多，建议定期清理未使用依赖并区分运行依赖与开发依赖。")
    if duplicates:
        score -= 1
        suggestions.append("检测到疑似重复依赖，建议统一依赖声明位置。")
    if flat_deps and unpinned_count / max(1, len(flat_deps)) > 0.55:
        score -= 1.5
        suggestions.append("较多依赖未固定版本，生产环境建议固定关键依赖版本。")

    return {
        "score": round(max(0, score), 1),
        "dependency_count": len(flat_deps),
        "dependency_files": sorted(dependency_files.keys()),
        "pinned_count": pinned_count,
        "unpinned_count": unpinned_count,
        "duplicates": duplicates[:20],
        "runtime_vs_dev_split": _runtime_dev_split(dependencies),
        "limitations": "未接入漏洞数据库，当前仅基于依赖数量、版本固定情况和依赖文件规范性进行规则型健康度评估。",
        "suggestions": suggestions or ["依赖声明较清晰，后续可接入 pip-audit、npm audit 或 OSV 数据库。"],
    }


def _is_pinned(spec: str) -> bool:
    clean = spec.strip()
    return any(pattern.search(clean) for pattern in PINNED_PATTERNS) or "==" in clean


def _runtime_dev_split(dependencies: dict[str, list[str]]) -> dict[str, Any]:
    groups = set(dependencies.keys())
    return {
        "has_runtime_group": bool(groups & {"python", "node", "java", "go", "rust"}),
        "has_dev_group": bool(groups & {"dev", "devDependencies", "optionalDependencies"}),
        "groups": sorted(groups),
    }
