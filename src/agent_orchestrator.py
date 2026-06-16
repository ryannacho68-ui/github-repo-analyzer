from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents import (
    ArchitectureAgent,
    CodeQualityAgent,
    DocumentationAgent,
    OverviewAgent,
    RiskAgent,
    SummaryAgent,
    TechStackAgent,
    TestDeployAgent,
)
from .context_builder import build_repository_context


def run_agent_workflow(analysis: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper for the new tool-using Agent architecture.

    Older code called this function after static modules had already run. The
    current implementation rebuilds RepositoryContext and lets each Agent own
    its analysis dimension by calling the relevant tools.
    """
    repo_info = analysis.get("repo_info") or {}
    if not repo_info.get("local_path"):
        return {"logs": [], "summary": {}, "total_elapsed_ms": 0, "total_token_estimate": 0}

    context = build_repository_context(repo_info, analysis.get("github_api") or {})
    shared: dict[str, Any] = {
        "github_api": analysis.get("github_api") or {},
        "repo_info": repo_info,
        "agent_results": {},
    }
    logs = []
    for agent in [
        TechStackAgent(),
        ArchitectureAgent(),
        OverviewAgent(),
        CodeQualityAgent(),
        DocumentationAgent(),
        TestDeployAgent(),
        RiskAgent(),
        SummaryAgent(),
    ]:
        result, log = agent.run(context, shared)
        shared["agent_results"][result.agent_name] = result
        logs.append(log)

    return {
        "logs": logs,
        "summary": shared.get("final_summary") or {},
        "results": {name: result.to_dict() for name, result in shared.get("agent_results", {}).items()},
        "facts": {
            "file_tree": shared.get("file_tree") or {},
            "tech_stack": shared.get("tech_stack") or {},
            "architecture": shared.get("architecture") or {},
        },
        "total_elapsed_ms": round(sum(item["elapsed_ms"] for item in logs), 2),
        "total_token_estimate": sum(item["token_estimate"] for item in logs),
    }
