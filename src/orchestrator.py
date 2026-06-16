from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .agents import (
    ArchitectureAgent,
    CodeQualityAgent,
    ComparisonAgent,
    DocumentationAgent,
    OverviewAgent,
    RiskAgent,
    SummaryAgent,
    TechStackAgent,
    TestDeployAgent,
)
from .context_builder import build_repository_context
from .github_api_client import fetch_github_api_snapshot
from .llm_client import DEFAULT_BASE_URL, DEFAULT_MODEL, OllamaClient
from .repo_loader import clone_or_use_cache


ProgressFn = Callable[[str, int], None]


def analyze_repository(
    repo_url: str,
    base_dir: Path,
    refresh: bool = False,
    use_llm: bool = True,
    model: str = DEFAULT_MODEL,
    ollama_base_url: str = DEFAULT_BASE_URL,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Run GitHub fetch, clone/cache, context building, and hybrid agents."""
    _progress(progress, "通过 GitHub API 获取仓库信息、README 和远程文件树", 8)
    github_api = fetch_github_api_snapshot(repo_url)

    _progress(progress, "克隆仓库或读取本地缓存", 18)
    repo_info = clone_or_use_cache(repo_url, base_dir, refresh=refresh).to_dict()

    _progress(progress, "构建 RepositoryContext：README、依赖、测试、部署和源码抽样", 28)
    context = build_repository_context(repo_info, github_api)

    llm_client = OllamaClient(model=model or DEFAULT_MODEL, base_url=ollama_base_url, timeout=75, enabled=use_llm)
    shared: dict[str, Any] = {
        "github_api": github_api,
        "repo_info": repo_info,
        "agent_results": {},
        "llm_client": llm_client,
        "use_llm": use_llm,
        "model": model or DEFAULT_MODEL,
    }
    logs = []
    agents = [
        (TechStackAgent(), 38),
        (ArchitectureAgent(), 48),
        (OverviewAgent(), 58),
        (CodeQualityAgent(), 68),
        (DocumentationAgent(), 76),
        (TestDeployAgent(), 84),
        (RiskAgent(), 91),
        (SummaryAgent(), 96),
    ]
    for agent, percent in agents:
        _progress(progress, f"{agent.name} 正在调用工具并分析证据", percent)
        result, log = agent.run(context, shared)
        shared["agent_results"][result.agent_name] = result
        logs.append(log)

    final_summary = shared.get("final_summary") or {}
    agents_payload = {
        "logs": logs,
        "summary": final_summary,
        "results": {name: result.to_dict() for name, result in shared.get("agent_results", {}).items()},
        "total_elapsed_ms": round(sum(item["elapsed_ms"] for item in logs), 2),
        "total_token_estimate": sum(item["token_estimate"] for item in logs),
    }

    analysis = {
        "repo_info": repo_info,
        "github_api": github_api,
        "context": context.to_dict(),
        "file_tree": shared.get("file_tree") or {},
        "tech_stack": shared.get("tech_stack") or {},
        "project_overview": shared.get("project_overview") or {},
        "overview": shared.get("project_overview") or {},
        "architecture": shared.get("architecture") or {},
        "code_quality": shared.get("code_quality") or {},
        "documentation": shared.get("documentation") or {},
        "test_deploy": shared.get("test_deploy") or {},
        "dependency_health": shared.get("dependency_health") or {},
        "security": shared.get("risks") or {},
        "risks": shared.get("risks") or {},
        "dimension_scores": shared.get("dimension_scores") or {},
        "final_summary": final_summary,
        "markdown_report": final_summary.get("markdown_report", ""),
        "agents": agents_payload,
        "agent_logs": logs,
    }
    _progress(progress, "单仓库 Agent 分析完成", 100)
    return analysis


def compare_repositories(
    repo_url_a: str,
    repo_url_b: str,
    base_dir: Path,
    refresh: bool = False,
    use_llm: bool = True,
    model: str = DEFAULT_MODEL,
    ollama_base_url: str = DEFAULT_BASE_URL,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    _progress(progress, "分析仓库 A", 5)
    repo_a = analyze_repository(
        repo_url_a,
        base_dir,
        refresh=refresh,
        use_llm=use_llm,
        model=model,
        ollama_base_url=ollama_base_url,
        progress=lambda message, percent: _progress(progress, f"仓库 A：{message}", min(45, max(5, round(percent * 0.45)))),
    )
    _progress(progress, "分析仓库 B", 50)
    repo_b = analyze_repository(
        repo_url_b,
        base_dir,
        refresh=refresh,
        use_llm=use_llm,
        model=model,
        ollama_base_url=ollama_base_url,
        progress=lambda message, percent: _progress(progress, f"仓库 B：{message}", 50 + min(40, max(0, round(percent * 0.40)))),
    )
    _progress(progress, "Comparison Agent 正在生成横向对比", 94)
    comparison = ComparisonAgent(
        llm_client=OllamaClient(model=model or DEFAULT_MODEL, base_url=ollama_base_url, timeout=75, enabled=use_llm)
    ).analyze(repo_a, repo_b).to_dict()
    _progress(progress, "双仓库对比完成", 100)
    return {
        "repo_a_analysis": repo_a,
        "repo_b_analysis": repo_b,
        "comparison": comparison,
        "agent_logs": (repo_a.get("agent_logs") or []) + (repo_b.get("agent_logs") or []) + comparison.get("agent_logs", []),
    }


def _progress(progress: ProgressFn | None, message: str, percent: int) -> None:
    if progress:
        progress(message, percent)
