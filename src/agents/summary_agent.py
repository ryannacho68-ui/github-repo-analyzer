from __future__ import annotations

from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from .base_agent import BaseAgent, score_to_confidence


DIMENSIONS = [
    "项目概览",
    "技术栈识别",
    "架构分析",
    "代码规模",
    "代码质量",
    "文档完整性",
    "依赖健康度",
    "测试覆盖",
    "部署方式",
    "潜在问题",
]


class SummaryAgent(BaseAgent):
    name = "汇总 Agent"
    input_summary = "All AgentResult outputs + shared tool facts"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        agent_results = shared.get("agent_results") or {}
        dimension_scores = build_dimension_scores(agent_results, shared)
        overall = round(sum(dimension_scores.values()) / len(dimension_scores), 1)
        strengths = _strengths(agent_results, dimension_scores)
        issues = _issues(agent_results, dimension_scores)
        suggestions = _suggestions(agent_results)
        summary = {
            "overall_score": overall,
            "dimension_scores": dimension_scores,
            "strengths": strengths,
            "issues": issues,
            "suggestions": suggestions,
            "ten_dimensions": _ten_dimension_outputs(agent_results, shared),
        }
        shared["dimension_scores"] = dimension_scores
        shared["final_summary"] = summary
        findings = [
            f"总体评分 {overall}/10。",
            f"优势维度：{', '.join(strengths[:3]) if strengths else '暂无明显优势'}。",
            f"主要问题：{', '.join(issues[:3]) if issues else '暂无明显问题'}。",
        ]
        evidence = [
            {"type": "dimension_scores", "value": dimension_scores},
            {"type": "agent_outputs", "agents": list(agent_results.keys())},
        ]
        return self.build_result(
            summary=f"已汇总 {len(DIMENSIONS)} 个维度，总体评分 {overall}/10。",
            findings=findings,
            evidence=evidence,
            score=overall,
            suggestions=suggestions,
            confidence=score_to_confidence(overall),
            raw_output=summary,
        )


def build_dimension_scores(agent_results: dict[str, AgentResult], shared: dict[str, Any]) -> dict[str, float]:
    overview = _score(agent_results, "项目概览 Agent")
    tech = _score(agent_results, "技术栈 Agent")
    architecture = _score(agent_results, "架构分析 Agent")
    quality = _score(agent_results, "代码质量 Agent")
    docs = _score(agent_results, "文档 Agent")
    test_deploy = shared.get("test_deploy") or {}
    dependency_health = shared.get("dependency_health") or {}
    risks = shared.get("risks") or {}
    file_tree = shared.get("file_tree") or {}
    scale_score = _scale_score(file_tree, test_deploy)
    potential_score = round((risks.get("score", 0) or 0) / 10, 1)
    return {
        "项目概览": overview,
        "技术栈识别": tech,
        "架构分析": architecture,
        "代码规模": scale_score,
        "代码质量": quality,
        "文档完整性": docs,
        "依赖健康度": dependency_health.get("score", 0),
        "测试覆盖": (test_deploy.get("tests") or {}).get("score", 0),
        "部署方式": (test_deploy.get("deployment") or {}).get("score", 0),
        "潜在问题": potential_score,
    }


def _ten_dimension_outputs(agent_results: dict[str, AgentResult], shared: dict[str, Any]) -> dict[str, Any]:
    return {
        "项目概览": _agent_dict(agent_results, "项目概览 Agent"),
        "技术栈识别": _agent_dict(agent_results, "技术栈 Agent"),
        "架构分析": _agent_dict(agent_results, "架构分析 Agent"),
        "代码规模": _code_scale(shared),
        "代码质量": _agent_dict(agent_results, "代码质量 Agent"),
        "文档完整性": _agent_dict(agent_results, "文档 Agent"),
        "依赖健康度": shared.get("dependency_health") or {},
        "测试覆盖": (shared.get("test_deploy") or {}).get("tests") or {},
        "部署方式": (shared.get("test_deploy") or {}).get("deployment") or {},
        "潜在问题": shared.get("risks") or {},
    }


def _score(agent_results: dict[str, AgentResult], name: str) -> float:
    result = agent_results.get(name)
    return result.score if result else 0.0


def _agent_dict(agent_results: dict[str, AgentResult], name: str) -> dict[str, Any]:
    result = agent_results.get(name)
    return result.to_dict() if result else {}


def _scale_score(file_tree: dict[str, Any], test_deploy: dict[str, Any]) -> float:
    files = file_tree.get("total_files", 0) or 0
    lines = file_tree.get("total_code_lines", 0) or 0
    tests = (test_deploy.get("tests") or {}).get("test_file_count", 0) or 0
    score = 5.0
    if files:
        score += 1.5
    if lines > 500:
        score += 1
    if tests:
        score += 1
    if files > 2000 or lines > 200_000:
        score -= 1
    return round(max(0, min(10, score)), 1)


def _code_scale(shared: dict[str, Any]) -> dict[str, Any]:
    file_tree = shared.get("file_tree") or {}
    test_deploy = shared.get("test_deploy") or {}
    return {
        "total_files": file_tree.get("total_files", 0),
        "total_dirs": file_tree.get("total_dirs", 0),
        "total_code_lines": file_tree.get("total_code_lines", 0),
        "language_line_counts": file_tree.get("language_line_counts", {}),
        "directory_summary": (file_tree.get("directory_summary") or [])[:12],
        "test_file_count": (test_deploy.get("tests") or {}).get("test_file_count", 0),
        "config_file_hint": len((file_tree.get("extension_counts") or {}).keys()),
    }


def _strengths(agent_results: dict[str, AgentResult], scores: dict[str, float]) -> list[str]:
    strengths = [dimension for dimension, score in scores.items() if score >= 8]
    for result in agent_results.values():
        if result.score >= 8:
            strengths.append(result.summary)
    return strengths[:8]


def _issues(agent_results: dict[str, AgentResult], scores: dict[str, float]) -> list[str]:
    issues = [f"{dimension} 得分偏低（{score}/10）" for dimension, score in scores.items() if score < 6]
    for result in agent_results.values():
        if result.score < 6:
            issues.extend(result.findings[:1])
    return issues[:10]


def _suggestions(agent_results: dict[str, AgentResult]) -> list[str]:
    suggestions = []
    for result in agent_results.values():
        suggestions.extend(result.suggestions[:3])
    return list(dict.fromkeys(suggestions))[:16]
