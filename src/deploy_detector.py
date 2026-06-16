from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def detect_deployment(repo_path: Path, context: dict[str, Any] | None = None) -> dict[str, Any]:
    repo_path = Path(repo_path)
    deploy_files = (context or {}).get("deploy_files") or []
    readme_text = ((context or {}).get("readme_text") or "").lower()
    scripts = _package_scripts(repo_path)
    env_examples = [
        path.name
        for path in repo_path.iterdir()
        if path.is_file() and path.name.lower() in {".env.example", ".env.sample", "env.example"}
    ]

    has_dockerfile = (repo_path / "Dockerfile").exists()
    has_compose = (repo_path / "docker-compose.yml").exists() or (repo_path / "docker-compose.yaml").exists()
    has_ci = (repo_path / ".github" / "workflows").exists()
    has_deploy_docs = any(keyword in readme_text for keyword in ["deploy", "deployment", "docker", "部署", "上线"])
    score = 10.0
    suggestions = []
    if not has_dockerfile and not has_compose:
        score -= 2
        suggestions.append("未检测到 Dockerfile 或 docker-compose，部署环境可复现性较弱。")
    if not has_ci:
        score -= 1.5
        suggestions.append("未检测到 GitHub Actions 等 CI/CD 配置。")
    if not env_examples:
        score -= 1
        suggestions.append("未检测到 .env.example，建议提供环境变量示例。")
    if not has_deploy_docs:
        score -= 1.5
        suggestions.append("README 中部署说明不足。")
    if not scripts:
        score -= 1
        suggestions.append("未检测到 package.json scripts 等启动脚本。")

    return {
        "score": round(max(0, score), 1),
        "dockerfile": has_dockerfile,
        "docker_compose": has_compose,
        "github_actions": has_ci,
        "deploy_files": deploy_files,
        "env_examples": env_examples,
        "startup_scripts": scripts,
        "has_deploy_docs": has_deploy_docs,
        "suggestions": suggestions or ["部署相关信号较完整，可补充生产环境参数说明。"],
    }


def _package_scripts(repo_path: Path) -> dict[str, str]:
    package_path = repo_path / "package.json"
    if not package_path.exists():
        return {}
    try:
        data = json.loads(package_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    scripts = data.get("scripts") or {}
    return {key: str(value) for key, value in scripts.items() if re.search(r"start|dev|serve|build|test", key, re.I)}
