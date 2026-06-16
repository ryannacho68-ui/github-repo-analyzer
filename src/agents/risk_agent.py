from __future__ import annotations

from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..dependency_checker import check_dependency_health
from ..security_scanner import scan_repository_risks
from .base_agent import BaseAgent, score_to_confidence


class RiskAgent(BaseAgent):
    name = "风险 Agent"
    input_summary = "dependency_checker.py + security_scanner.py + quality/doc/test gaps"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        dependency_health = check_dependency_health(context.local_path, shared.get("tech_stack") or {}, context.to_dict())
        risks = scan_repository_risks(context.local_path, dependency_health)
        shared["dependency_health"] = dependency_health
        shared["risks"] = risks
        score = round(min(dependency_health.get("score", 0), (risks.get("score", 0) or 0) / 10), 1)
        evidence = [
            {"type": "dependency_health", "value": dependency_health},
            {"type": "security_risks", "items": (risks.get("risks") or [])[:12]},
            {"type": "rule_note", "text": risks.get("rule_note")},
        ]
        findings = [
            f"依赖数量 {dependency_health.get('dependency_count', 0)}，未固定版本约 {dependency_health.get('unpinned_count', 0)} 个。",
            risks.get("summary", "未生成风险摘要。"),
            dependency_health.get("limitations", "未接入漏洞数据库。"),
        ]
        suggestions = (dependency_health.get("suggestions") or []) + [
            risk.get("message", "") for risk in (risks.get("risks") or [])[:5]
        ]
        return self.build_result(
            summary=f"依赖健康与潜在风险评分 {score}/10。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=[item for item in suggestions if item],
            confidence=score_to_confidence(score),
            raw_output={"dependency_health": dependency_health, "risks": risks},
            tools_used=["dependency_checker.py", "security_scanner.py"],
        )
