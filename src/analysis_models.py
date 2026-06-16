from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


@dataclass
class RepositoryContext:
    repo_name: str
    owner: str
    url: str
    local_path: str
    readme_text: str = ""
    readme_summary: str = ""
    file_tree: dict[str, Any] = field(default_factory=dict)
    dependency_files: dict[str, str] = field(default_factory=dict)
    source_samples: list[dict[str, Any]] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    deploy_files: list[str] = field(default_factory=list)
    language_stats: dict[str, Any] = field(default_factory=dict)
    code_metrics: dict[str, Any] = field(default_factory=dict)
    import_summary: dict[str, Any] = field(default_factory=dict)
    possible_entry_files: list[str] = field(default_factory=list)
    entrypoint_candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass
class AgentResult:
    agent_name: str
    summary: str
    findings: list[str]
    evidence: list[dict[str, Any]]
    score: float
    suggestions: list[str]
    confidence: str
    raw_output: dict[str, Any] = field(default_factory=dict)
    llm_used: bool = False
    tools_used: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    status: str = "done"
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass
class RepositoryAnalysisResult:
    repo_info: dict[str, Any]
    overview: dict[str, Any]
    architecture: dict[str, Any]
    tech_stack: dict[str, Any]
    code_quality: dict[str, Any]
    documentation: dict[str, Any]
    test_deploy: dict[str, Any]
    risks: dict[str, Any]
    dependency_health: dict[str, Any]
    dimension_scores: dict[str, float]
    final_summary: dict[str, Any]
    agent_logs: list[dict[str, Any]]
    markdown_report: str = ""
    json_report_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass
class ComparisonResult:
    repo_a: dict[str, Any]
    repo_b: dict[str, Any]
    overall_conclusion: str
    dimension_comparison: list[dict[str, Any]]
    winner_by_dimension: dict[str, str]
    tech_stack_comparison: dict[str, Any]
    architecture_comparison: dict[str, Any]
    quality_comparison: dict[str, Any]
    documentation_test_deploy_comparison: dict[str, Any]
    risk_comparison: dict[str, Any]
    scenario_recommendations: dict[str, str]
    suggestions: dict[str, list[str]]
    markdown_report: str = ""
    json_report_path: str = ""
    agent_logs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))
