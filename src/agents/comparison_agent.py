from __future__ import annotations

from typing import Any

from ..analysis_models import ComparisonResult


class ComparisonAgent:
    name = "对比 Agent"

    def analyze(self, repo_a: dict[str, Any], repo_b: dict[str, Any]) -> ComparisonResult:
        scores_a = repo_a.get("dimension_scores") or {}
        scores_b = repo_b.get("dimension_scores") or {}
        dimensions = list(dict.fromkeys(list(scores_a.keys()) + list(scores_b.keys())))
        comparison = []
        winners: dict[str, str] = {}
        for dimension in dimensions:
            score_a = round(scores_a.get(dimension, 0), 1)
            score_b = round(scores_b.get(dimension, 0), 1)
            winner = _winner(score_a, score_b, repo_a, repo_b)
            winners[dimension] = winner
            comparison.append(
                {
                    "分析维度": dimension,
                    "仓库 A 得分": score_a,
                    "仓库 B 得分": score_b,
                    "胜出方": winner,
                    "简要原因": _reason(dimension, score_a, score_b, repo_a, repo_b),
                }
            )

        overall = _overall_conclusion(repo_a, repo_b, comparison)
        return ComparisonResult(
            repo_a=_repo_brief(repo_a),
            repo_b=_repo_brief(repo_b),
            overall_conclusion=overall,
            dimension_comparison=comparison,
            winner_by_dimension=winners,
            tech_stack_comparison=_tech_stack_comparison(repo_a, repo_b),
            architecture_comparison=_architecture_comparison(repo_a, repo_b),
            quality_comparison=_quality_comparison(repo_a, repo_b),
            documentation_test_deploy_comparison=_doc_test_deploy_comparison(repo_a, repo_b),
            risk_comparison=_risk_comparison(repo_a, repo_b),
            scenario_recommendations=_scenario_recommendations(repo_a, repo_b),
            suggestions={
                "repo_a": _summary_suggestions(repo_a),
                "repo_b": _summary_suggestions(repo_b),
                "common": _common_suggestions(repo_a, repo_b),
            },
            agent_logs=[
                {
                    "agent": self.name,
                    "input": "repo_a_analysis + repo_b_analysis",
                    "output": {"overall_conclusion": overall, "dimension_comparison": comparison},
                    "elapsed_ms": 0,
                    "token_estimate": 0,
                    "status": "done",
                }
            ],
        )


def _repo_brief(repo: dict[str, Any]) -> dict[str, Any]:
    info = repo.get("repo_info") or {}
    overview = repo.get("project_overview") or {}
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
    return f"{dimension} 得分更高，主要依据：{'; '.join((summary.get('strengths') or [])[:2]) or '结构化评分更优'}。"


def _overall_conclusion(repo_a: dict[str, Any], repo_b: dict[str, Any], comparison: list[dict[str, Any]]) -> str:
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
    return ((repo.get("final_summary") or {}).get("suggestions") or [])[:8]


def _common_suggestions(repo_a: dict[str, Any], repo_b: dict[str, Any]) -> list[str]:
    low_dims = []
    for dimension in (repo_a.get("dimension_scores") or {}).keys():
        if (repo_a.get("dimension_scores") or {}).get(dimension, 0) < 7 and (repo_b.get("dimension_scores") or {}).get(dimension, 0) < 7:
            low_dims.append(f"两者都可加强 {dimension}。")
    return low_dims[:8] or ["两者共同问题不明显，建议继续结合人工评审。"]
