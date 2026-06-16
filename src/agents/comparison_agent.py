from __future__ import annotations

import json
import time
from typing import Any

from ..analysis_models import ComparisonResult
from ..llm_client import OllamaClient


class ComparisonAgent:
    name = "对比 Agent"

    def __init__(self, llm_client: OllamaClient | None = None) -> None:
        self.llm_client = llm_client

    def analyze(self, repo_a: dict[str, Any], repo_b: dict[str, Any]) -> ComparisonResult:
        start = time.perf_counter()
        comparison = _dimension_comparison(repo_a, repo_b)
        fallback = _fallback_payload(repo_a, repo_b, comparison)
        if self.llm_client:
            llm_payload = self.llm_client.generate_json(
                system_prompt=(
                    "你是 GitHub 仓库横向对比 Agent。只能基于两个仓库已有结构化分析结果生成结论。"
                    "不能编造缺失信息；某维度证据不足时写“不确定”。"
                ),
                user_prompt=_comparison_prompt(repo_a, repo_b, fallback),
                fallback=fallback,
            )
        else:
            llm_payload = {**fallback, "_llm_meta": {"llm_used": False, "status": "no_client", "error_message": ""}}

        result_payload = _normalize_payload(llm_payload, fallback)
        meta = result_payload.get("_llm_meta") or {}
        elapsed_seconds = round(time.perf_counter() - start, 3)
        agent_log = {
            "agent": self.name,
            "agent_name": self.name,
            "input": "repo_a_analysis + repo_b_analysis",
            "input_summary": "Two RepositoryAnalysisResult JSON payloads",
            "tools_used": ["dimension score comparison", "Ollama generate_json"],
            "llm_used": bool(meta.get("llm_used")),
            "model": meta.get("model"),
            "output_summary": result_payload.get("overall_conclusion", ""),
            "evidence_count": len(result_payload.get("dimension_comparison") or []),
            "score": None,
            "output": {
                "overall_conclusion": result_payload.get("overall_conclusion"),
                "dimension_comparison": result_payload.get("dimension_comparison"),
            },
            "elapsed_ms": round(elapsed_seconds * 1000, 2),
            "elapsed_seconds": elapsed_seconds,
            "token_estimate": max(1, round(len(str(result_payload)) / 4)),
            "status": meta.get("status", "done"),
            "error_message": meta.get("error_message", ""),
        }
        return ComparisonResult(
            repo_a=_repo_brief(repo_a),
            repo_b=_repo_brief(repo_b),
            overall_conclusion=result_payload["overall_conclusion"],
            dimension_comparison=result_payload["dimension_comparison"],
            winner_by_dimension=result_payload["winner_by_dimension"],
            tech_stack_comparison=result_payload["tech_stack_comparison"],
            architecture_comparison=result_payload["architecture_comparison"],
            quality_comparison=result_payload["quality_comparison"],
            documentation_test_deploy_comparison=result_payload["documentation_test_deploy_comparison"],
            risk_comparison=result_payload["risk_comparison"],
            scenario_recommendations=result_payload["scenario_recommendations"],
            suggestions=result_payload["suggestions"],
            markdown_report=result_payload["markdown_report"],
            agent_logs=[agent_log],
        )


def _dimension_comparison(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> list[dict[str, Any]]:
    scores_a = repo_a.get("dimension_scores") or {}
    scores_b = repo_b.get("dimension_scores") or {}
    dimensions = list(dict.fromkeys(list(scores_a.keys()) + list(scores_b.keys())))
    rows = []
    for dimension in dimensions:
        score_a = round(scores_a.get(dimension, 0), 1)
        score_b = round(scores_b.get(dimension, 0), 1)
        rows.append(
            {
                "分析维度": dimension,
                "仓库 A 得分": score_a,
                "仓库 B 得分": score_b,
                "胜出方": _winner(score_a, score_b, repo_a, repo_b),
                "简要原因": _reason(dimension, score_a, score_b, repo_a, repo_b),
            }
        )
    return rows


def _fallback_payload(repo_a: dict[str, Any], repo_b: dict[str, Any], comparison: list[dict[str, Any]]) -> dict[str, Any]:
    scenario = _scenario_recommendations(repo_a, repo_b)
    suggestions = {
        "repo_a": _summary_suggestions(repo_a),
        "repo_b": _summary_suggestions(repo_b),
        "common": _common_suggestions(repo_a, repo_b),
    }
    payload = {
        "repo_a": _repo_brief(repo_a),
        "repo_b": _repo_brief(repo_b),
        "overall_conclusion": _overall_conclusion(repo_a, repo_b),
        "dimension_comparison": comparison,
        "winner_by_dimension": {row["分析维度"]: row["胜出方"] for row in comparison},
        "tech_stack_comparison": _tech_stack_comparison(repo_a, repo_b),
        "architecture_comparison": _architecture_comparison(repo_a, repo_b),
        "quality_comparison": _quality_comparison(repo_a, repo_b),
        "documentation_test_deploy_comparison": _doc_test_deploy_comparison(repo_a, repo_b),
        "risk_comparison": _risk_comparison(repo_a, repo_b),
        "scenario_recommendations": scenario,
        "learning_recommendation": scenario.get("learning"),
        "redevelopment_recommendation": scenario.get("secondary_development"),
        "production_recommendation": scenario.get("production"),
        "repo_a_suggestions": suggestions["repo_a"],
        "repo_b_suggestions": suggestions["repo_b"],
        "suggestions": suggestions,
    }
    payload["markdown_report"] = _comparison_markdown(payload)
    return payload


def _comparison_prompt(repo_a: dict[str, Any], repo_b: dict[str, Any], fallback: dict[str, Any]) -> str:
    payload = {
        "repo_a": _compact_analysis(repo_a),
        "repo_b": _compact_analysis(repo_b),
        "rule_comparison": fallback,
        "required_json_fields": [
            "overall_conclusion",
            "dimension_comparison",
            "winner_by_dimension",
            "tech_stack_comparison",
            "architecture_comparison",
            "quality_comparison",
            "documentation_test_deploy_comparison",
            "risk_comparison",
            "learning_recommendation",
            "redevelopment_recommendation",
            "production_recommendation",
            "repo_a_suggestions",
            "repo_b_suggestions",
            "markdown_report",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(fallback)
    for key in (
        "overall_conclusion",
        "dimension_comparison",
        "winner_by_dimension",
        "tech_stack_comparison",
        "architecture_comparison",
        "quality_comparison",
        "documentation_test_deploy_comparison",
        "risk_comparison",
        "scenario_recommendations",
        "suggestions",
        "markdown_report",
    ):
        if payload.get(key):
            result[key] = payload[key]

    if payload.get("learning_recommendation"):
        result.setdefault("scenario_recommendations", {})["learning"] = payload["learning_recommendation"]
    if payload.get("redevelopment_recommendation"):
        result.setdefault("scenario_recommendations", {})["secondary_development"] = payload["redevelopment_recommendation"]
    if payload.get("production_recommendation"):
        result.setdefault("scenario_recommendations", {})["production"] = payload["production_recommendation"]
    if payload.get("repo_a_suggestions"):
        result.setdefault("suggestions", {})["repo_a"] = payload["repo_a_suggestions"]
    if payload.get("repo_b_suggestions"):
        result.setdefault("suggestions", {})["repo_b"] = payload["repo_b_suggestions"]
    result["_llm_meta"] = payload.get("_llm_meta") or {}
    if not result.get("markdown_report"):
        result["markdown_report"] = _comparison_markdown(result)
    return result


def _repo_brief(repo: dict[str, Any]) -> dict[str, Any]:
    info = repo.get("repo_info") or {}
    overview = repo.get("project_overview") or repo.get("overview") or {}
    return {
        "name": info.get("name"),
        "owner": info.get("owner"),
        "url": info.get("web_url"),
        "project_type": overview.get("project_type"),
        "overall_score": (repo.get("final_summary") or {}).get("overall_score"),
    }


def _winner(score_a: float, score_b: float, repo_a: dict[str, Any], repo_b: dict[str, Any]) -> str:
    if abs(score_a - score_b) < 0.4:
        return "接近"
    return f"A: {(repo_a.get('repo_info') or {}).get('name')}" if score_a > score_b else f"B: {(repo_b.get('repo_info') or {}).get('name')}"


def _reason(dimension: str, score_a: float, score_b: float, repo_a: dict[str, Any], repo_b: dict[str, Any]) -> str:
    if abs(score_a - score_b) < 0.4:
        return "两者该维度得分接近，建议结合具体业务场景选择。"
    better = repo_a if score_a > score_b else repo_b
    summary = better.get("final_summary") or {}
    return f"{dimension} 得分更高，依据：{'; '.join((summary.get('strengths') or [])[:2]) or '结构化评分更优'}。"


def _overall_conclusion(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> str:
    score_a = (repo_a.get("final_summary") or {}).get("overall_score", 0)
    score_b = (repo_b.get("final_summary") or {}).get("overall_score", 0)
    name_a = (repo_a.get("repo_info") or {}).get("name", "仓库 A")
    name_b = (repo_b.get("repo_info") or {}).get("name", "仓库 B")
    if abs(score_a - score_b) < 0.4:
        return f"{name_a} 与 {name_b} 总体成熟度接近，应根据技术栈和目标场景选择。"
    mature = name_a if score_a > score_b else name_b
    return f"{mature} 的综合评分更高，整体成熟度、可维护性或工程规范表现更稳。"


def _tech_stack_comparison(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> dict[str, Any]:
    tech_a = repo_a.get("tech_stack") or {}
    tech_b = repo_b.get("tech_stack") or {}
    return {
        "language": [tech_a.get("main_language"), tech_b.get("main_language")],
        "frameworks_a": tech_a.get("frameworks") or [],
        "frameworks_b": tech_b.get("frameworks") or [],
        "databases_a": tech_a.get("databases") or [],
        "databases_b": tech_b.get("databases") or [],
        "tools_a": tech_a.get("tools") or [],
        "tools_b": tech_b.get("tools") or [],
    }


def _architecture_comparison(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> dict[str, Any]:
    arch_a = repo_a.get("architecture") or {}
    arch_b = repo_b.get("architecture") or {}
    return {
        "pattern_a": arch_a.get("pattern"),
        "pattern_b": arch_b.get("pattern"),
        "entry_a": arch_a.get("entry_points") or [],
        "entry_b": arch_b.get("entry_points") or [],
        "modules_a": arch_a.get("modules") or [],
        "modules_b": arch_b.get("modules") or [],
    }


def _quality_comparison(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> dict[str, Any]:
    qa = repo_a.get("code_quality") or {}
    qb = repo_b.get("code_quality") or {}
    return {
        "score_a": qa.get("score"),
        "score_b": qb.get("score"),
        "deductions_a": qa.get("deductions") or [],
        "deductions_b": qb.get("deductions") or [],
    }


def _doc_test_deploy_comparison(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> dict[str, Any]:
    return {
        "documentation_a": repo_a.get("documentation") or {},
        "documentation_b": repo_b.get("documentation") or {},
        "test_deploy_a": repo_a.get("test_deploy") or {},
        "test_deploy_b": repo_b.get("test_deploy") or {},
    }


def _risk_comparison(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> dict[str, Any]:
    return {
        "risks_a": (repo_a.get("security") or {}).get("risk_counts", {}),
        "risks_b": (repo_b.get("security") or {}).get("risk_counts", {}),
        "dependency_health_a": repo_a.get("dependency_health") or {},
        "dependency_health_b": repo_b.get("dependency_health") or {},
    }


def _scenario_recommendations(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> dict[str, str]:
    name_a = (repo_a.get("repo_info") or {}).get("name", "仓库 A")
    name_b = (repo_b.get("repo_info") or {}).get("name", "仓库 B")
    scores_a = repo_a.get("dimension_scores") or {}
    scores_b = repo_b.get("dimension_scores") or {}
    learning = name_a if scores_a.get("文档完整性", 0) + scores_a.get("项目概览", 0) >= scores_b.get("文档完整性", 0) + scores_b.get("项目概览", 0) else name_b
    development = name_a if scores_a.get("架构分析", 0) + scores_a.get("代码质量", 0) >= scores_b.get("架构分析", 0) + scores_b.get("代码质量", 0) else name_b
    deployment = name_a if scores_a.get("部署方式", 0) + scores_a.get("潜在问题", 0) >= scores_b.get("部署方式", 0) + scores_b.get("潜在问题", 0) else name_b
    return {
        "learning": f"学习优先看 {learning}，因为文档/概览信号更好。",
        "secondary_development": f"二次开发优先考虑 {development}，因为架构和代码质量维度更稳。",
        "production": f"部署上线优先考虑 {deployment}，因为部署与风险维度更有优势。",
        "course_reference": f"课程设计参考可优先选择 {learning} 的表达方式，并结合另一个仓库的工程实践。",
    }


def _summary_suggestions(repo: dict[str, Any]) -> list[str]:
    return ((repo.get("final_summary") or {}).get("suggestions") or (repo.get("final_summary") or {}).get("improvement_suggestions") or [])[:8]


def _common_suggestions(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> list[str]:
    low_dims = []
    for dimension in (repo_a.get("dimension_scores") or {}).keys():
        if (repo_a.get("dimension_scores") or {}).get(dimension, 0) < 7 and (repo_b.get("dimension_scores") or {}).get(dimension, 0) < 7:
            low_dims.append(f"两者都可加强 {dimension}。")
    return low_dims[:8] or ["两者共同问题不明显，建议继续结合人工评审。"]


def _comparison_markdown(payload: dict[str, Any]) -> str:
    repo_a = payload.get("repo_a") or {}
    repo_b = payload.get("repo_b") or {}
    rows = "\n".join(
        f"| {row.get('分析维度')} | {row.get('仓库 A 得分')} | {row.get('仓库 B 得分')} | {row.get('胜出方')} | {row.get('简要原因')} |"
        for row in payload.get("dimension_comparison") or []
    )
    return f"""# 仓库对比分析报告

## 1. 对比对象

- 仓库 A：{repo_a.get('owner')}/{repo_a.get('name')}，{repo_a.get('url')}，项目类型：{repo_a.get('project_type')}
- 仓库 B：{repo_b.get('owner')}/{repo_b.get('name')}，{repo_b.get('url')}，项目类型：{repo_b.get('project_type')}

## 2. 总体结论

{payload.get('overall_conclusion', '暂无总体结论。')}

## 3. 维度评分对比

| 分析维度 | 仓库 A 得分 | 仓库 B 得分 | 胜出方 | 简要原因 |
|---|---:|---:|---|---|
{rows}

## 4. 技术栈对比

```json
{json.dumps(payload.get('tech_stack_comparison') or {}, ensure_ascii=False, indent=2)}
```

## 5. 架构对比

```json
{json.dumps(payload.get('architecture_comparison') or {}, ensure_ascii=False, indent=2)}
```

## 6. 文档、测试、部署与风险

```json
{json.dumps({
    'documentation_test_deploy_comparison': payload.get('documentation_test_deploy_comparison') or {},
    'risk_comparison': payload.get('risk_comparison') or {},
}, ensure_ascii=False, indent=2)}
```

## 7. 适用场景建议
{_dict_bullets(payload.get('scenario_recommendations') or {})}

## 8. 改进建议

### 仓库 A
{_bullet_lines((payload.get('suggestions') or {}).get('repo_a') or [])}

### 仓库 B
{_bullet_lines((payload.get('suggestions') or {}).get('repo_b') or [])}
"""


def _compact_analysis(repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo_info": repo.get("repo_info") or {},
        "project_overview": repo.get("project_overview") or {},
        "tech_stack": repo.get("tech_stack") or {},
        "architecture": repo.get("architecture") or {},
        "code_quality": _compact(repo.get("code_quality") or {}),
        "documentation": _compact(repo.get("documentation") or {}),
        "test_deploy": _compact(repo.get("test_deploy") or {}),
        "dependency_health": repo.get("dependency_health") or {},
        "security": _compact(repo.get("security") or {}),
        "dimension_scores": repo.get("dimension_scores") or {},
        "final_summary": _compact(repo.get("final_summary") or {}),
    }


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in list(value.items())[:24] if key != "_llm_meta"}
    if isinstance(value, list):
        return [_compact(item) for item in value[:10]]
    if isinstance(value, str):
        return value[:1000]
    return value


def _bullet_lines(items: list[Any]) -> str:
    return "\n".join(f"- {item}" for item in items if item) or "- 暂无。"


def _dict_bullets(items: dict[str, Any]) -> str:
    return "\n".join(f"- {key}: {value}" for key, value in items.items()) or "- 暂无。"
