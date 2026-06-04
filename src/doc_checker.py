from __future__ import annotations

import re
from pathlib import Path


def check_documentation(repo_path: Path) -> dict:
    repo_path = Path(repo_path)
    readme_path = _find_first(repo_path, ["README.md", "README.rst", "README.txt", "readme.md"])
    readme_text = _read_text(readme_path) if readme_path else ""

    checks = {
        "readme_exists": readme_path is not None,
        "has_project_intro": _has_intro(readme_text),
        "has_installation": _contains_any(
            readme_text,
            ["install", "installation", "pip install", "npm install", "安装", "环境配置"],
        ),
        "has_run_instructions": _contains_any(
            readme_text,
            ["run", "start", "usage", "streamlit run", "python ", "启动", "运行"],
        ),
        "has_usage_example": _contains_any(
            readme_text,
            ["example", "demo", "screenshot", "usage", "示例", "演示", "用法"],
        ),
        "has_license": _find_first(repo_path, ["LICENSE", "LICENSE.md", "license"]) is not None,
        "has_dependency_file": (repo_path / "requirements.txt").exists()
        or (repo_path / "pyproject.toml").exists(),
        "has_gitignore": (repo_path / ".gitignore").exists(),
    }

    weights = {
        "readme_exists": 25,
        "has_project_intro": 15,
        "has_installation": 15,
        "has_run_instructions": 15,
        "has_usage_example": 10,
        "has_license": 10,
        "has_dependency_file": 5,
        "has_gitignore": 5,
    }
    score = sum(weight for key, weight in weights.items() if checks[key])
    suggestions = _build_suggestions(checks)

    return {
        "score": score,
        "checks": checks,
        "readme_path": readme_path.name if readme_path else None,
        "readme_word_count": len(re.findall(r"\w+", readme_text)),
        "suggestions": suggestions,
    }


def _build_suggestions(checks: dict[str, bool]) -> list[str]:
    suggestions = []
    if not checks["readme_exists"]:
        suggestions.append("补充 README.md，说明项目目标、安装、运行和示例。")
    if checks["readme_exists"] and not checks["has_project_intro"]:
        suggestions.append("在 README 开头补充项目背景、核心能力和适用场景。")
    if not checks["has_installation"]:
        suggestions.append("增加安装依赖步骤，例如 pip install -r requirements.txt。")
    if not checks["has_run_instructions"]:
        suggestions.append("增加本地启动命令和必要环境变量说明。")
    if not checks["has_usage_example"]:
        suggestions.append("补充使用示例、截图或演示流程，降低新人理解成本。")
    if not checks["has_license"]:
        suggestions.append("增加 LICENSE，明确项目的使用和分发许可。")
    if not checks["has_dependency_file"]:
        suggestions.append("提供 requirements.txt 或 pyproject.toml，方便复现实验环境。")
    if not checks["has_gitignore"]:
        suggestions.append("增加 .gitignore，避免提交缓存、虚拟环境和敏感文件。")
    if not suggestions:
        suggestions.append("文档要素较完整，可以继续补充架构图和常见问题。")
    return suggestions


def _find_first(repo_path: Path, names: list[str]) -> Path | None:
    exact_names = {name.lower() for name in names}
    try:
        for child in repo_path.iterdir():
            if child.is_file() and child.name.lower() in exact_names:
                return child
    except OSError:
        return None
    return None


def _read_text(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in keywords)


def _has_intro(text: str) -> bool:
    if len(text.strip()) < 120:
        return False
    return _contains_any(text, ["overview", "introduction", "about", "简介", "项目", "功能", "背景"])

