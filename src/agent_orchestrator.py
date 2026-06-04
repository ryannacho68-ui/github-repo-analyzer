from __future__ import annotations

import json
import time
from typing import Any, Callable


AgentFn = Callable[[dict[str, Any]], dict[str, Any]]


def run_agent_workflow(analysis: dict[str, Any]) -> dict[str, Any]:
    """Create deterministic multi-agent style outputs from analysis facts."""
    agent_specs: list[tuple[str, str, AgentFn]] = [
        ("架构分析 Agent", "项目文件结构 + 技术栈 + 入口文件候选", _architecture_agent),
        ("技术栈 Agent", "依赖配置 + 后缀统计 + GitHub API 语言", _tech_stack_agent),
        ("代码质量 Agent", "AST 指标 + TODO + 测试目录 + 长函数", _quality_agent),
        ("文档 Agent", "README + LICENSE + 安装/运行/示例检查", _documentation_agent),
        ("汇总 Agent", "以上 Agent 结构化输出", _summary_agent),
    ]

    logs = []
    outputs = {}
    for name, input_summary, fn in agent_specs:
        start = time.perf_counter()
        output = fn({**analysis, "agent_outputs": outputs})
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        token_estimate = _estimate_tokens({"input": input_summary, "output": output})
        outputs[name] = output
        logs.append(
            {
                "agent": name,
                "input": input_summary,
                "output": output,
                "elapsed_ms": elapsed_ms,
                "token_estimate": token_estimate,
                "status": "done",
            }
        )

    return {
        "logs": logs,
        "summary": outputs.get("汇总 Agent", {}),
        "total_elapsed_ms": round(sum(item["elapsed_ms"] for item in logs), 2),
        "total_token_estimate": sum(item["token_estimate"] for item in logs),
    }


def _architecture_agent(analysis: dict[str, Any]) -> dict[str, Any]:
    architecture = analysis.get("architecture") or {}
    return {
        "pattern": architecture.get("pattern", "Unknown"),
        "confidence": architecture.get("confidence", 0),
        "entry": architecture.get("entry_points", []),
        "modules": architecture.get("modules", []),
        "rationale": architecture.get("rationale", []),
    }


def _tech_stack_agent(analysis: dict[str, Any]) -> dict[str, Any]:
    tech = analysis.get("tech_stack") or {}
    github_api = analysis.get("github_api") or {}
    return {
        "language": tech.get("main_language") or github_api.get("repo", {}).get("language") or "Unknown",
        "frameworks": tech.get("frameworks") or [],
        "tools": tech.get("tools") or [],
        "dependencies": {
            key: values[:15] for key, values in (tech.get("dependencies") or {}).items()
        },
        "dependency_versions": {
            key: values[:15] for key, values in (tech.get("dependency_versions") or {}).items()
        },
        "evidence": tech.get("indicators") or [],
    }


def _quality_agent(analysis: dict[str, Any]) -> dict[str, Any]:
    quality = analysis.get("code_quality") or {}
    py = quality.get("python") or {}
    return {
        "score": round((quality.get("score", 0) or 0) / 10, 1),
        "score_100": quality.get("score", 0),
        "functions": py.get("functions", 0),
        "classes": py.get("classes", 0),
        "average_function_length": py.get("average_function_length", 0),
        "issues": quality.get("deductions") or [],
        "long_functions": py.get("long_functions", [])[:5],
        "tests": quality.get("tests") or {},
    }


def _documentation_agent(analysis: dict[str, Any]) -> dict[str, Any]:
    docs = analysis.get("documentation") or {}
    return {
        "score": round((docs.get("score", 0) or 0) / 10, 1),
        "score_100": docs.get("score", 0),
        "checks": docs.get("checks") or {},
        "suggestions": docs.get("suggestions") or [],
        "readme_word_count": docs.get("readme_word_count", 0),
    }


def _summary_agent(analysis: dict[str, Any]) -> dict[str, Any]:
    outputs = analysis.get("agent_outputs") or {}
    security = analysis.get("security") or {}
    file_tree = analysis.get("file_tree") or {}
    overview = analysis.get("project_overview") or {}
    return {
        "purpose": overview.get("purpose", ""),
        "content_type": overview.get("project_type", "Unknown"),
        "target_users": overview.get("target_users", ""),
        "architecture_pattern": outputs.get("架构分析 Agent", {}).get("pattern", "Unknown"),
        "main_language": outputs.get("技术栈 Agent", {}).get("language", "Unknown"),
        "quality_score": outputs.get("代码质量 Agent", {}).get("score", 0),
        "doc_score": outputs.get("文档 Agent", {}).get("score", 0),
        "file_count": file_tree.get("total_files", 0),
        "code_lines": file_tree.get("total_code_lines", 0),
        "risk_counts": security.get("risk_counts", {}),
        "key_findings": _key_findings(analysis, outputs),
    }


def _key_findings(analysis: dict[str, Any], outputs: dict[str, Any]) -> list[str]:
    findings = []
    overview = analysis.get("project_overview") or {}
    architecture = outputs.get("架构分析 Agent", {})
    tech = outputs.get("技术栈 Agent", {})
    quality = outputs.get("代码质量 Agent", {})
    docs = outputs.get("文档 Agent", {})
    security = analysis.get("security") or {}
    if overview.get("purpose"):
        findings.append(f"项目用途：{overview.get('purpose')}")
    if overview.get("project_type"):
        findings.append(f"项目类型：{overview.get('project_type')}，目标用户：{overview.get('target_users', '开发者')}。")
    findings.append(f"架构模式判断为：{architecture.get('pattern', 'Unknown')}。")
    findings.append(f"主要技术栈：{tech.get('language', 'Unknown')} / {', '.join(tech.get('frameworks') or ['未识别框架'])}。")
    findings.append(f"代码质量评分：{quality.get('score', 0)}/10。")
    findings.append(f"文档完整性评分：{docs.get('score', 0)}/10。")
    if security.get("risks"):
        findings.append(f"安全与工程规范风险：{len(security.get('risks', []))} 项。")
    else:
        findings.append("未发现明显安全与工程规范风险。")
    return findings


def _estimate_tokens(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    return max(1, round(len(text) / 4))
