from __future__ import annotations

import json
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
    input_summary = "All AgentResult JSON outputs + shared tool facts"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        agent_results = shared.get("agent_results") or {}
        dimension_scores = build_dimension_scores(agent_results, shared)
        fallback_summary = _fallback_summary(context, agent_results, shared, dimension_scores)
        client = shared.get("llm_client")
        if client:
            llm_payload = client.generate_json(
                system_prompt=(
                    "你是 GitHub 仓库分析汇总 Agent。只能基于各 Agent 的结构化 JSON 和证据生成最终报告。"
                    "不得重新分析未提供的源码，不得编造技术栈、漏洞、覆盖率或版本。"
                ),
                user_prompt=_summary_prompt(context, agent_results, shared, dimension_scores),
                fallback=fallback_summary,
            )
        else:
            llm_payload = {**fallback_summary, "_llm_meta": {"llm_used": False, "status": "no_client", "error_message": ""}}

        summary = _normalize_summary(llm_payload, fallback_summary, dimension_scores)
        shared["dimension_scores"] = dimension_scores
        shared["final_summary"] = summary
        meta = summary.get("_llm_meta") or {}
        findings = [
            f"总体评分 {summary.get('overall_score', 0)}/10",
            f"主要优势：{', '.join(summary.get('strengths') or ['暂无明确优势'])}",
            f"主要问题：{', '.join(summary.get('issues') or summary.get('weaknesses') or ['暂无明确问题'])}",
        ]
        evidence = summary.get("evidence_summary") or [
            {"type": "dimension_scores", "value": dimension_scores},
            {"type": "agent_outputs", "agents": list(agent_results.keys())},
        ]
        return self.build_result(
            summary=f"已汇总 {len(DIMENSIONS)} 个维度，总体评分 {summary.get('overall_score', 0)}/10。",
            findings=findings,
            evidence=evidence,
            score=summary.get("overall_score", 0),
            suggestions=summary.get("improvement_suggestions") or summary.get("suggestions") or [],
            confidence=score_to_confidence(summary.get("overall_score", 0)),
            raw_output=summary,
            llm_used=bool(meta.get("llm_used")),
            tools_used=["AgentResult JSON aggregation", "Ollama generate_json"],
            status=meta.get("status", "done"),
            error_message=meta.get("error_message", ""),
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


def _summary_prompt(
    context: RepositoryContext,
    agent_results: dict[str, AgentResult],
    shared: dict[str, Any],
    dimension_scores: dict[str, float],
) -> str:
    compact_results = {
        name: {
            "summary": result.summary,
            "findings": result.findings[:6],
            "evidence": result.evidence[:6],
            "score": result.score,
            "suggestions": result.suggestions[:6],
            "confidence": result.confidence,
            "raw_output": _compact(result.raw_output),
        }
        for name, result in agent_results.items()
    }
    payload = {
        "repo": {
            "name": context.repo_name,
            "owner": context.owner,
            "url": context.url,
        },
        "dimension_scores": dimension_scores,
        "agent_results": compact_results,
        "required_json_fields": [
            "final_summary",
            "overall_score",
            "strengths",
            "weaknesses",
            "issues",
            "improvement_suggestions",
            "markdown_report",
            "dimension_scores",
            "evidence_summary",
        ],
        "markdown_report_sections": [
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
            "总体评分",
            "主要优点",
            "主要问题",
            "改进建议",
            "Agent 协作日志摘要",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fallback_summary(
    context: RepositoryContext,
    agent_results: dict[str, AgentResult],
    shared: dict[str, Any],
    dimension_scores: dict[str, float],
) -> dict[str, Any]:
    overall = round(sum(dimension_scores.values()) / len(dimension_scores), 1) if dimension_scores else 0
    strengths = _strengths(agent_results, dimension_scores)
    issues = _issues(agent_results, dimension_scores)
    suggestions = _suggestions(agent_results)
    summary = {
        "final_summary": f"{context.owner}/{context.repo_name} 综合评分 {overall}/10。",
        "overall_score": overall,
        "dimension_scores": dimension_scores,
        "strengths": strengths,
        "weaknesses": issues,
        "issues": issues,
        "suggestions": suggestions,
        "improvement_suggestions": suggestions,
        "evidence_summary": [
            {"type": "dimension_scores", "value": dimension_scores},
            {"type": "agent_outputs", "agents": list(agent_results.keys())},
        ],
        "ten_dimensions": _ten_dimension_outputs(agent_results, shared),
    }
    summary["markdown_report"] = _template_markdown(context, summary)
    return summary


def _normalize_summary(payload: dict[str, Any], fallback: dict[str, Any], dimension_scores: dict[str, float]) -> dict[str, Any]:
    summary = dict(fallback)
    for key in ("final_summary", "strengths", "weaknesses", "issues", "suggestions", "improvement_suggestions", "evidence_summary"):
        if payload.get(key):
            summary[key] = payload[key]
    summary["overall_score"] = _numeric(payload.get("overall_score"), fallback.get("overall_score", 0))
    summary["dimension_scores"] = dimension_scores
    if payload.get("markdown_report"):
        summary["markdown_report"] = payload["markdown_report"]
    summary["_llm_meta"] = payload.get("_llm_meta") or {}
    return summary


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
    return list(dict.fromkeys(strengths))[:8]


def _issues(agent_results: dict[str, AgentResult], scores: dict[str, float]) -> list[str]:
    issues = [f"{dimension} 得分偏低（{score}/10）" for dimension, score in scores.items() if score < 6]
    for result in agent_results.values():
        if result.score < 6:
            issues.extend(result.findings[:1])
    return list(dict.fromkeys(issues))[:10]


def _suggestions(agent_results: dict[str, AgentResult]) -> list[str]:
    suggestions = []
    for result in agent_results.values():
        suggestions.extend(result.suggestions[:3])
    return list(dict.fromkeys(suggestions))[:16]


def _template_markdown(context: RepositoryContext, summary: dict[str, Any]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in (summary.get("dimension_scores") or {}).items())
    return f"""# {context.owner}/{context.repo_name} 仓库智能分析报告

## 总体评分

综合评分：{summary.get('overall_score', 0)}/10

| 分析维度 | 得分 |
|---|---:|
{rows}

## 主要优点
{_bullet_lines(summary.get('strengths') or ['暂无明确优势。'])}

## 主要问题
{_bullet_lines(summary.get('issues') or ['暂无明确问题。'])}

## 改进建议
{_bullet_lines(summary.get('suggestions') or ['继续完善 README、测试与部署说明。'])}

## Agent 协作日志摘要

本报告由规则工具先提取文件结构、依赖、代码质量、文档、测试部署和风险证据，再由 Summary Agent 汇总结构化 JSON 生成。
"""


def _bullet_lines(items: list[Any]) -> str:
    return "\n".join(f"- {item}" for item in items if item) or "- 暂无。"


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in list(value.items())[:30] if key != "_llm_meta"}
    if isinstance(value, list):
        return [_compact(item) for item in value[:12]]
    if isinstance(value, str):
        return value[:1200]
    return value


def _numeric(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(fallback or 0)
    if number > 10:
        number = number / 10
    return round(max(0.0, min(10.0, number)), 1)
