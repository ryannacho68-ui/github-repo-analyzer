from __future__ import annotations

from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..project_overview_analyzer import analyze_project_overview
from .base_agent import BaseAgent, score_to_confidence


class OverviewAgent(BaseAgent):
    name = "项目概览 Agent"
    input_summary = "README + GitHub metadata + tech stack + architecture facts"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        overview = analyze_project_overview(
            repo_path=context.local_path,
            github_api=shared.get("github_api") or {},
            tech_stack=shared.get("tech_stack") or {},
            file_tree=shared.get("file_tree") or {},
            architecture=shared.get("architecture") or {},
        )
        shared["project_overview"] = overview
        score = min(10, max(3, overview.get("confidence", 0) / 10))
        evidence = overview.get("evidence") or [
            {"source": "README", "text": context.readme_text[:240] or "README 缺失或内容不足"}
        ]
        findings = [
            f"项目类型：{overview.get('project_type', '不确定')}。",
            f"项目用途：{overview.get('purpose', '不确定')}。",
            f"目标用户：{overview.get('target_users', '不确定')}。",
        ]
        suggestions = []
        if overview.get("limitations"):
            suggestions.extend(overview.get("limitations") or [])
        return self.build_result(
            summary=overview.get("purpose") or "README/元信息不足，项目用途不确定。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions or ["项目概览证据较明确，可继续补充目标用户和场景说明。"],
            confidence=score_to_confidence(score),
            raw_output=overview,
        )
