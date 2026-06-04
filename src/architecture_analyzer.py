from __future__ import annotations

from pathlib import Path


ENTRY_CANDIDATES = [
    "app.py",
    "main.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "server.py",
    "index.js",
    "src/main.ts",
    "src/main.tsx",
    "src/App.jsx",
    "src/App.tsx",
    "pages/index.tsx",
]


def analyze_architecture(repo_path: Path, file_tree: dict, tech_stack: dict) -> dict:
    repo_path = Path(repo_path)
    top_dirs = {item["directory"] for item in file_tree.get("directory_summary", [])}
    frameworks = set(tech_stack.get("frameworks") or [])
    tools = set(tech_stack.get("tools") or [])

    entry_points = [
        candidate
        for candidate in ENTRY_CANDIDATES
        if (repo_path / candidate).exists()
    ]
    modules = _module_summary(top_dirs, repo_path)
    pattern, confidence, rationale = _infer_pattern(repo_path, top_dirs, frameworks, tools)

    return {
        "pattern": pattern,
        "confidence": confidence,
        "entry_points": entry_points,
        "modules": modules,
        "rationale": rationale,
        "style_tags": _style_tags(repo_path, top_dirs, frameworks, tools),
    }


def _infer_pattern(
    repo_path: Path,
    top_dirs: set[str],
    frameworks: set[str],
    tools: set[str],
) -> tuple[str, float, list[str]]:
    rationale: list[str] = []

    has_models = any(name in top_dirs for name in {"models", "model", "entities"})
    has_routes = any(name in top_dirs for name in {"routes", "views", "controllers", "blueprints"})
    has_templates = any(name in top_dirs for name in {"templates", "static"})
    if has_models and (has_routes or has_templates):
        rationale.append("检测到 models/routes/templates 等典型分层目录。")
        return "单体 MVC / 分层 Web 应用", 0.82, rationale

    if "React" in frameworks or "Vue" in frameworks or "Next.js" in frameworks:
        rationale.append("前端框架依赖与 src/components/pages 等目录匹配。")
        return "组件化前端应用", 0.78, rationale

    if "Docker Compose" in tools and _compose_service_count(repo_path) >= 2:
        rationale.append("docker-compose 中存在多个服务定义。")
        return "多服务 / 微服务候选", 0.68, rationale

    if (repo_path / "src").exists() and (repo_path / "tests").exists():
        rationale.append("src + tests 目录表明较标准的库或应用工程结构。")
        return "标准库式分层工程", 0.64, rationale

    if top_dirs:
        rationale.append("基于顶层目录做启发式判断，未发现明确 MVC 或微服务证据。")
        return "单体项目 / 通用工程结构", 0.52, rationale

    rationale.append("仓库文件较少，架构模式证据不足。")
    return "结构过小，暂无法判断", 0.35, rationale


def _module_summary(top_dirs: set[str], repo_path: Path) -> list[dict]:
    modules = []
    descriptions = {
        "src": "核心源码目录",
        "app": "应用主体模块",
        "routes": "路由层",
        "controllers": "控制器层",
        "models": "数据模型层",
        "templates": "模板视图层",
        "static": "静态资源",
        "tests": "测试目录",
        "docs": "项目文档",
        ".github": "GitHub CI/CD 配置",
        "scripts": "脚本工具",
        "config": "配置模块",
    }
    for directory in sorted(top_dirs):
        path = repo_path / directory
        if directory == "." or not path.exists():
            continue
        modules.append(
            {
                "name": directory,
                "role": descriptions.get(directory, "业务或工程辅助模块"),
            }
        )
    return modules[:20]


def _style_tags(
    repo_path: Path,
    top_dirs: set[str],
    frameworks: set[str],
    tools: set[str],
) -> list[str]:
    tags = []
    if frameworks:
        tags.append("框架驱动")
    if "Docker" in tools or "Docker Compose" in tools:
        tags.append("容器化")
    if "GitHub Actions" in tools:
        tags.append("CI/CD")
    if (repo_path / "tests").exists() or any(name.startswith("test") for name in top_dirs):
        tags.append("含测试")
    if any(name in top_dirs for name in {"models", "routes", "templates"}):
        tags.append("Web 分层")
    return tags or ["轻量仓库"]


def _compose_service_count(repo_path: Path) -> int:
    for filename in ("docker-compose.yml", "docker-compose.yaml"):
        path = repo_path / filename
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return 0
        if "services:" not in text:
            return 0
        return sum(1 for line in text.splitlines() if line.startswith("  ") and line.strip().endswith(":"))
    return 0

