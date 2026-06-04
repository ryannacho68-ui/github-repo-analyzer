from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


TYPE_RULES = [
    (
        "AI / 数据分析应用",
        ["streamlit", "gradio", "dashboard", "plotly", "pandas", "data analysis", "数据分析", "可视化"],
        "需要数据分析、可视化或交互式分析工具的用户",
    ),
    (
        "Web 后端 / API 服务",
        ["fastapi", "flask", "django", "express", "spring", "rest api", "api service", "后端", "接口"],
        "后端开发者、接口调用方和系统集成用户",
    ),
    (
        "前端应用",
        ["react", "vue", "next.js", "nuxt", "vite", "frontend", "前端", "组件"],
        "前端开发者和 Web 产品用户",
    ),
    (
        "命令行工具",
        ["cli", "command line", "terminal", "click", "argparse", "命令行", "终端"],
        "需要在终端中自动化任务的开发者",
    ),
    (
        "Python 库 / SDK",
        ["python package", "library", "sdk", "pypi", "pytest", "ruff", "mypy", "库", "工具包"],
        "希望复用该库能力的 Python 开发者",
    ),
    (
        "机器学习 / 深度学习项目",
        ["machine learning", "deep learning", "pytorch", "tensorflow", "model", "机器学习", "深度学习", "模型训练"],
        "算法工程师、数据科学学习者和模型使用者",
    ),
    (
        "插件 / Skill / 自动化脚本",
        ["skill", "plugin", "codex", "automation", "powershell", "脚本", "插件", "自动化"],
        "需要扩展工具能力或执行自动化流程的用户",
    ),
    (
        "文档 / 示例仓库",
        ["example", "sample", "demo", "hello world", "tutorial", "示例", "教程", "演示"],
        "学习者、课程演示者和新手开发者",
    ),
]


def analyze_project_overview(
    repo_path: Path,
    github_api: dict[str, Any],
    tech_stack: dict[str, Any],
    file_tree: dict[str, Any],
    architecture: dict[str, Any],
) -> dict[str, Any]:
    """Infer repository purpose from README, metadata, topics, and structural facts."""
    repo_path = Path(repo_path)
    api_repo = (github_api or {}).get("repo") or {}
    metadata = _local_metadata(repo_path)
    readme = _readme_text(repo_path) or ((github_api or {}).get("readme") or {}).get("excerpt", "")
    readme_title = _readme_title(readme)
    readme_sentences = _readme_summary_sentences(readme)

    evidence = []
    if api_repo.get("description"):
        evidence.append({"source": "GitHub API description", "text": api_repo["description"]})
    if metadata.get("description"):
        evidence.append({"source": metadata.get("source", "package metadata"), "text": metadata["description"]})
    if readme_title:
        evidence.append({"source": "README title", "text": readme_title})
    for sentence in readme_sentences[:3]:
        evidence.append({"source": "README excerpt", "text": sentence})
    if api_repo.get("topics"):
        evidence.append({"source": "GitHub topics", "text": ", ".join(api_repo.get("topics", [])[:12])})

    combined_text = " ".join(
        [
            api_repo.get("description", ""),
            metadata.get("description", ""),
            readme_title,
            " ".join(readme_sentences[:6]),
            " ".join(api_repo.get("topics") or []),
            " ".join(tech_stack.get("frameworks") or []),
            " ".join(tech_stack.get("tools") or []),
            architecture.get("pattern", ""),
        ]
    )
    project_type, target_users, matched_keywords = _classify_project(combined_text)
    purpose = _build_purpose(
        repo_path=repo_path,
        project_type=project_type,
        api_description=api_repo.get("description", ""),
        metadata_description=metadata.get("description", ""),
        readme_title=readme_title,
        readme_sentences=readme_sentences,
        tech_stack=tech_stack,
        file_tree=file_tree,
        architecture=architecture,
    )
    confidence = _confidence_score(evidence, matched_keywords, readme, metadata, api_repo)

    return {
        "name": metadata.get("name") or api_repo.get("full_name") or repo_path.name,
        "project_type": project_type,
        "purpose": purpose,
        "target_users": target_users,
        "confidence": confidence,
        "keywords": matched_keywords[:12],
        "readme_title": readme_title,
        "readme_excerpt": " ".join(readme_sentences[:4]),
        "evidence": evidence[:8],
        "limitations": _limitations(evidence, readme, api_repo),
    }


def _local_metadata(repo_path: Path) -> dict[str, str]:
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            data = json.loads(_read_text(package_json))
            return {
                "source": "package.json",
                "name": data.get("name") or "",
                "description": data.get("description") or "",
            }
        except json.JSONDecodeError:
            pass

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(_read_text(pyproject))
            project = data.get("project") or {}
            poetry = (data.get("tool") or {}).get("poetry") or {}
            return {
                "source": "pyproject.toml",
                "name": project.get("name") or poetry.get("name") or "",
                "description": project.get("description") or poetry.get("description") or "",
            }
        except Exception:
            pass

    setup_cfg = repo_path / "setup.cfg"
    if setup_cfg.exists():
        text = _read_text(setup_cfg)
        name = _metadata_line(text, "name")
        description = _metadata_line(text, "description")
        if name or description:
            return {"source": "setup.cfg", "name": name, "description": description}

    return {"source": "", "name": "", "description": ""}


def _classify_project(text: str) -> tuple[str, str, list[str]]:
    lower = text.lower()
    best_type = "通用代码仓库"
    best_target = "需要理解或复用该仓库的开发者"
    best_matches: list[str] = []
    for label, keywords, target in TYPE_RULES:
        matches = [keyword for keyword in keywords if keyword.lower() in lower]
        if len(matches) > len(best_matches):
            best_type = label
            best_target = target
            best_matches = matches
    return best_type, best_target, best_matches


def _build_purpose(
    repo_path: Path,
    project_type: str,
    api_description: str,
    metadata_description: str,
    readme_title: str,
    readme_sentences: list[str],
    tech_stack: dict[str, Any],
    file_tree: dict[str, Any],
    architecture: dict[str, Any],
) -> str:
    description = _clean_sentence(api_description or metadata_description)
    if description:
        return description

    if readme_sentences:
        return _clean_sentence(readme_sentences[0])

    title = readme_title or repo_path.name
    language = tech_stack.get("main_language") or "Unknown"
    frameworks = ", ".join((tech_stack.get("frameworks") or [])[:3])
    architecture_name = architecture.get("pattern") or "通用工程结构"
    size_hint = f"{file_tree.get('total_files', 0)} 个文件"
    framework_hint = f"，使用 {frameworks}" if frameworks else ""
    return f"{title} 是一个{project_type}，主要语言为 {language}{framework_hint}，结构上接近 {architecture_name}，当前仓库规模约 {size_hint}。"


def _readme_text(repo_path: Path) -> str:
    for name in ("README.md", "README.rst", "README.txt", "readme.md"):
        path = repo_path / name
        if path.exists():
            return _read_text(path)
    return ""


def _readme_title(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith("#"):
            return clean.lstrip("#").strip()
        if clean and len(clean) < 120:
            return clean
    return ""


def _readme_summary_sentences(text: str) -> list[str]:
    cleaned_lines = []
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith(("-", "*", "|", ">", "`")):
            continue
        if re.match(r"^\W*$", line):
            continue
        cleaned_lines.append(re.sub(r"\s+", " ", line))

    paragraph = " ".join(cleaned_lines[:12])
    if not paragraph:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s+", paragraph)
    return [_clean_sentence(part) for part in parts if _useful_sentence(part)][:6]


def _confidence_score(
    evidence: list[dict[str, str]],
    matched_keywords: list[str],
    readme: str,
    metadata: dict[str, str],
    api_repo: dict[str, Any],
) -> int:
    score = 25
    if api_repo.get("description"):
        score += 20
    if metadata.get("description"):
        score += 18
    if readme and len(readme) > 200:
        score += 20
    if matched_keywords:
        score += min(18, len(matched_keywords) * 4)
    if len(evidence) >= 3:
        score += 10
    return min(100, score)


def _limitations(evidence: list[dict[str, str]], readme: str, api_repo: dict[str, Any]) -> list[str]:
    limitations = []
    if not api_repo.get("description"):
        limitations.append("GitHub 仓库描述为空，项目用途主要依赖 README 和代码结构推断。")
    if not readme or len(readme) < 120:
        limitations.append("README 内容较少，项目用途判断置信度会降低。")
    if not evidence:
        limitations.append("缺少可用于内容概览的文本证据。")
    return limitations or ["项目用途判断有 README 或元信息支撑。"]


def _metadata_line(text: str, key: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _clean_sentence(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:420]


def _useful_sentence(text: str) -> bool:
    clean = _clean_sentence(text)
    if len(clean) < 25:
        return False
    lower = clean.lower()
    if lower.startswith(("http://", "https://")):
        return False
    if lower.count("/") > 8:
        return False
    return True


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 1_500_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""

