from __future__ import annotations

import json
from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..project_overview_analyzer import analyze_project_overview
from .base_agent import BaseAgent, score_to_confidence


class OverviewAgent(BaseAgent):
    name = "项目概览 Agent"
    input_summary = "README summary + GitHub metadata + file tree summary + entrypoint candidates"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        fallback = analyze_project_overview(
            repo_path=context.local_path,
            github_api=shared.get("github_api") or {},
            tech_stack=shared.get("tech_stack") or {},
            file_tree=shared.get("file_tree") or {},
            architecture=shared.get("architecture") or {},
        )
        fallback_payload = _fallback_payload(context, shared, fallback)
        client = shared.get("llm_client")
        if client:
            llm_payload = client.generate_json(
                system_prompt=(
                    "你是 GitHub 仓库项目概览分析 Agent。只能根据用户提供的 README、GitHub 元数据、"
                    "文件结构和依赖文件名判断项目用途。信息不足时必须写“不确定”，并说明缺少哪些证据。"
                ),
                user_prompt=_overview_prompt(context, shared, fallback),
                fallback=fallback_payload,
            )
        else:
            llm_payload = {**fallback_payload, "_llm_meta": {"llm_used": False, "status": "no_client", "error_message": ""}}

        overview = _normalize_overview(llm_payload, fallback)
        shared["project_overview"] = overview
        meta = overview.get("_llm_meta") or {}
        score = _score(overview.get("score"), fallback.get("confidence", 0) / 10)
        evidence = overview.get("evidence") or fallback.get("evidence") or [
            {"source": "README", "text": context.readme_text[:240] or "README 缺失或内容不足"}
        ]
        findings = [
            f"项目类型：{overview.get('project_type', '不确定')}",
            f"项目用途：{overview.get('purpose', '不确定')}",
            f"目标用户：{overview.get('target_users', '不确定')}",
        ]
        suggestions = overview.get("suggestions") or fallback.get("limitations") or [
            "继续补充 README 中的项目用途、目标用户和核心功能说明。"
        ]
        return self.build_result(
            summary=overview.get("purpose") or "项目信息不足，项目用途不确定。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions,
            confidence=overview.get("confidence") or score_to_confidence(score),
            raw_output=overview,
            llm_used=bool(meta.get("llm_used")),
            tools_used=["project_overview_analyzer.py", "Ollama generate_json"],
            status=meta.get("status", "done"),
            error_message=meta.get("error_message", ""),
        )


def _overview_prompt(context: RepositoryContext, shared: dict[str, Any], fallback: dict[str, Any]) -> str:
    file_tree = shared.get("file_tree") or {}
    github_repo = (shared.get("github_api") or {}).get("repo") or {}
    payload = {
        "repo_name": context.repo_name,
        "owner": context.owner,
        "url": context.url,
        "github_description": github_repo.get("description"),
        "github_topics": github_repo.get("topics") or [],
        "readme_summary": context.readme_summary or context.readme_text[:1800],
        "file_tree_excerpt": (file_tree.get("tree") or "")[:6000],
        "entrypoint_candidates": context.entrypoint_candidates or context.possible_entry_files,
        "dependency_files": sorted(context.dependency_files.keys()),
        "rule_fallback": fallback,
        "required_json_fields": [
            "project_name",
            "project_type",
            "project_purpose",
            "solved_problem",
            "target_users",
            "core_features",
            "evidence",
            "score",
            "confidence",
            "suggestions",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fallback_payload(context: RepositoryContext, shared: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_name": fallback.get("name") or context.repo_name,
        "project_type": fallback.get("project_type") or "不确定",
        "project_purpose": fallback.get("purpose") or "不确定",
        "solved_problem": fallback.get("purpose") or "不确定",
        "target_users": fallback.get("target_users") or "不确定",
        "core_features": _feature_hints(shared),
        "evidence": fallback.get("evidence") or [],
        "score": round((fallback.get("confidence", 0) or 0) / 10, 1),
        "confidence": score_to_confidence((fallback.get("confidence", 0) or 0) / 10),
        "suggestions": fallback.get("limitations") or ["README 信息有限，项目用途存在不确定性。"],
    }


def _normalize_overview(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = {
        "name": payload.get("project_name") or fallback.get("name"),
        "project_type": payload.get("project_type") or fallback.get("project_type") or "不确定",
        "purpose": payload.get("project_purpose") or payload.get("purpose") or fallback.get("purpose") or "不确定",
        "solved_problem": payload.get("solved_problem") or "不确定",
        "target_users": payload.get("target_users") or fallback.get("target_users") or "不确定",
        "core_features": payload.get("core_features") or [],
        "confidence": payload.get("confidence") or score_to_confidence(_score(payload.get("score"), 5)),
        "score": _score(payload.get("score"), (fallback.get("confidence", 0) or 0) / 10),
        "evidence": payload.get("evidence") or fallback.get("evidence") or [],
        "suggestions": payload.get("suggestions") or fallback.get("limitations") or [],
        "keywords": fallback.get("keywords") or [],
        "readme_title": fallback.get("readme_title", ""),
        "readme_excerpt": fallback.get("readme_excerpt", ""),
        "limitations": fallback.get("limitations") or [],
        "_llm_meta": payload.get("_llm_meta") or {},
    }
    if not result["evidence"]:
        result["evidence"] = [{"source": "limitation", "text": "缺少 README 或明确元数据，项目概览不确定。"}]
    return result


def _feature_hints(shared: dict[str, Any]) -> list[str]:
    tech = shared.get("tech_stack") or {}
    frameworks = tech.get("frameworks") or []
    tools = tech.get("tools") or []
    return [f"检测到 {item}" for item in (frameworks + tools)[:6]]


def _score(value: Any, fallback: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = float(fallback or 0)
    if score > 10:
        score = score / 10
    return round(max(0.0, min(10.0, score)), 1)
