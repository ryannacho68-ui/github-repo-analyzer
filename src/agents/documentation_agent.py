from __future__ import annotations

from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..doc_checker import check_documentation
from .base_agent import BaseAgent, score_to_confidence


class DocumentationAgent(BaseAgent):
    name = "文档 Agent"
    input_summary = "doc_checker.py + README API excerpt + docs/API/deploy doc signals"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        docs = check_documentation(context.local_path)
        api_doc = _api_doc_signals(context, shared)
        docs["api_documentation"] = api_doc
        shared["documentation"] = docs
        score = round((docs.get("score", 0) or 0) / 10, 1)
        if not api_doc["has_api_docs"]:
            score = max(0, score - 0.7)
        evidence = [
            {"type": "readme_path", "path": docs.get("readme_path")},
            {"type": "checks", "value": docs.get("checks") or {}},
            {"type": "api_documentation", "value": api_doc},
            {"type": "docs_dir", "exists": "docs" in {item.split('/')[0] for item in context.config_files + context.deploy_files}},
        ]
        findings = [
            f"README：{'存在' if (docs.get('checks') or {}).get('readme_exists') else '缺失'}，词数约 {docs.get('readme_word_count', 0)}。",
            f"安装/运行/示例检查：{_doc_check_summary(docs.get('checks') or {})}。",
            f"API 文档：{'存在相关信号' if api_doc['has_api_docs'] else '未检测到明确 API 文档'}。",
        ]
        suggestions = list(docs.get("suggestions") or [])
        if not api_doc["has_api_docs"]:
            suggestions.append("如果项目提供接口，建议补充 API.md、OpenAPI/Swagger 或 README 接口示例。")
        return self.build_result(
            summary=f"文档完整性评分 {score}/10。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions,
            confidence=score_to_confidence(score),
            raw_output=docs,
            tools_used=["doc_checker.py", "GitHub README API"],
        )


def _api_doc_signals(context: RepositoryContext, shared: dict[str, Any]) -> dict[str, Any]:
    candidates = {"openapi.json", "openapi.yaml", "swagger.json", "swagger.yaml", "api.md", "API.md", "docs/api.md", "docs/API.md"}
    files = [path for path in context.config_files if path in candidates or path.lower().endswith(("api.md", "openapi.yaml", "swagger.yaml"))]
    readme_text = (context.readme_text or "").lower()
    readme_mentions = any(keyword in readme_text for keyword in ["api", "endpoint", "route", "openapi", "swagger", "接口"])
    github_readme_available = bool(((shared.get("github_api") or {}).get("readme") or {}).get("available"))
    return {
        "has_api_docs": bool(files or readme_mentions),
        "files": files,
        "readme_mentions_api": readme_mentions,
        "github_readme_available": github_readme_available,
    }


def _doc_check_summary(checks: dict[str, bool]) -> str:
    labels = {
        "has_installation": "安装",
        "has_run_instructions": "运行",
        "has_usage_example": "示例",
    }
    return "，".join(f"{label}{'有' if checks.get(key) else '缺'}" for key, label in labels.items())
