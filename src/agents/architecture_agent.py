from __future__ import annotations

import json
from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..architecture_analyzer import analyze_architecture
from ..file_tree import analyze_file_tree
from .base_agent import BaseAgent, score_to_confidence


class ArchitectureAgent(BaseAgent):
    name = "架构分析 Agent"
    input_summary = "file_tree.py + architecture_analyzer.py + entry files + directory roles"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        file_tree = shared.setdefault("file_tree", analyze_file_tree(context.local_path))
        tech_stack = shared.get("tech_stack") or {}
        rule_architecture = analyze_architecture(context.local_path, file_tree, tech_stack)
        context.file_tree = file_tree

        fallback_payload = _fallback_payload(context, file_tree, tech_stack, rule_architecture)
        client = shared.get("llm_client")
        if client:
            llm_payload = client.generate_json(
                system_prompt=(
                    "你是 GitHub 仓库架构分析 Agent。必须先尊重规则工具给出的文件树、入口文件、目录职责和技术栈证据，"
                    "再判断架构模式、模块划分和设计风险。不能直接假设未提供的源码细节；证据不足时写“不确定”。"
                ),
                user_prompt=_architecture_prompt(context, file_tree, tech_stack, rule_architecture),
                fallback=fallback_payload,
            )
        else:
            llm_payload = {**fallback_payload, "_llm_meta": {"llm_used": False, "status": "no_client", "error_message": ""}}

        architecture = _normalize_architecture(llm_payload, fallback_payload)
        shared["architecture"] = architecture
        modules = architecture.get("modules") or []
        score = round((architecture.get("confidence", 0) or 0) * 10, 1)
        evidence = [
            {"type": "entry_points", "paths": architecture.get("entry_points") or context.possible_entry_files},
            {"type": "directory_summary", "items": (file_tree.get("directory_summary") or [])[:12]},
            {"type": "rationale", "items": architecture.get("rationale") or []},
            {"type": "llm_meta", "value": architecture.get("_llm_meta") or {}},
        ]
        findings = [
            f"结构模式判断为 {architecture.get('pattern', 'Unknown')}。",
            f"识别到 {len(modules)} 个主要模块/目录职责。",
            f"入口文件：{', '.join(architecture.get('entry_points') or ['未识别到明确入口'])}。",
        ]
        if architecture.get("architecture_summary"):
            findings.append(f"架构说明：{architecture.get('architecture_summary')}")
        suggestions = architecture.get("suggestions") or _rule_suggestions(architecture, score)
        meta = architecture.get("_llm_meta") or {}
        return self.build_result(
            summary=f"{architecture.get('pattern', 'Unknown')}，置信度 {score}/10。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions or ["架构结构较清晰，可补充架构图和核心调用流程。"],
            confidence=score_to_confidence(score),
            raw_output=architecture,
            llm_used=bool(meta.get("llm_used")),
            tools_used=["file_tree.py", "architecture_analyzer.py", "Ollama generate_json"],
            status=meta.get("status", "done"),
            error_message=meta.get("error_message", ""),
        )


def _architecture_prompt(
    context: RepositoryContext,
    file_tree: dict[str, Any],
    tech_stack: dict[str, Any],
    rule_architecture: dict[str, Any],
) -> str:
    payload = {
        "repo": {
            "name": context.repo_name,
            "owner": context.owner,
            "url": context.url,
        },
        "readme_summary": context.readme_summary or context.readme_text[:1200],
        "tech_stack": {
            "main_language": tech_stack.get("main_language"),
            "frameworks": tech_stack.get("frameworks") or [],
            "tools": tech_stack.get("tools") or [],
        },
        "file_tree": {
            "total_files": file_tree.get("total_files", 0),
            "total_dirs": file_tree.get("total_dirs", 0),
            "total_code_lines": file_tree.get("total_code_lines", 0),
            "directory_summary": (file_tree.get("directory_summary") or [])[:16],
            "tree_excerpt": (file_tree.get("tree") or "")[:6000],
        },
        "entrypoint_candidates": context.entrypoint_candidates or context.possible_entry_files,
        "source_sample_paths": [item.get("path") for item in (context.source_samples or [])[:12] if item.get("path")],
        "rule_architecture": rule_architecture,
        "required_json_fields": [
            "pattern",
            "architecture_summary",
            "confidence",
            "entry_points",
            "modules",
            "rationale",
            "style_tags",
            "design_risks",
            "suggestions",
        ],
        "output_rules": [
            "confidence 使用 0-1 之间的小数",
            "modules 使用列表，每项包含 name 和 role",
            "rationale 必须引用目录、入口文件、技术栈或 README 证据",
            "不要编造未在输入中出现的数据库、服务或模块",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fallback_payload(
    context: RepositoryContext,
    file_tree: dict[str, Any],
    tech_stack: dict[str, Any],
    rule_architecture: dict[str, Any],
) -> dict[str, Any]:
    score = round((rule_architecture.get("confidence", 0) or 0) * 10, 1)
    return {
        "pattern": rule_architecture.get("pattern", "Unknown"),
        "architecture_summary": _rule_summary(context, file_tree, tech_stack, rule_architecture),
        "confidence": rule_architecture.get("confidence", 0),
        "entry_points": rule_architecture.get("entry_points") or context.entrypoint_candidates or context.possible_entry_files,
        "modules": rule_architecture.get("modules") or [],
        "rationale": rule_architecture.get("rationale") or [],
        "style_tags": rule_architecture.get("style_tags") or [],
        "design_risks": _rule_design_risks(rule_architecture, score),
        "suggestions": _rule_suggestions(rule_architecture, score),
        "score": score,
    }


def _normalize_architecture(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    confidence = _confidence_ratio(payload.get("confidence"), fallback.get("confidence", 0))
    modules = _normalize_modules(payload.get("modules") or fallback.get("modules") or [])
    return {
        "pattern": _text(payload.get("pattern") or payload.get("architecture_pattern") or fallback.get("pattern") or "Unknown"),
        "architecture_summary": _text(payload.get("architecture_summary") or payload.get("summary") or ""),
        "confidence": confidence,
        "entry_points": _as_text_list(payload.get("entry_points")) or fallback.get("entry_points") or [],
        "modules": modules,
        "rationale": _as_text_list(payload.get("rationale")) or fallback.get("rationale") or [],
        "style_tags": _as_text_list(payload.get("style_tags")) or fallback.get("style_tags") or [],
        "design_risks": _as_text_list(payload.get("design_risks")),
        "suggestions": _as_text_list(payload.get("suggestions")),
        "rule_pattern": fallback.get("pattern"),
        "rule_confidence": fallback.get("confidence", 0),
        "_llm_meta": payload.get("_llm_meta") or {},
    }


def _normalize_modules(value: Any) -> list[dict[str, str]]:
    modules = []
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, dict):
            name = _text(item.get("name") or item.get("directory") or item.get("module") or "未命名模块")
            role = _text(item.get("role") or item.get("responsibility") or item.get("description") or "职责不确定")
        else:
            name = _text(item)
            role = "职责不确定"
        if name:
            modules.append({"name": name, "role": role})
    return modules[:24]


def _rule_summary(
    context: RepositoryContext,
    file_tree: dict[str, Any],
    tech_stack: dict[str, Any],
    rule_architecture: dict[str, Any],
) -> str:
    language = tech_stack.get("main_language") or "Unknown"
    files = file_tree.get("total_files", 0)
    pattern = rule_architecture.get("pattern", "Unknown")
    return f"{context.owner}/{context.repo_name} 基于 {language}，规则分析判断为 {pattern}，仓库约 {files} 个文件。"


def _rule_design_risks(architecture: dict[str, Any], score: float) -> list[str]:
    risks = []
    if score < 6:
        risks.append("目录结构证据较弱，架构模式置信度偏低。")
    if not architecture.get("entry_points"):
        risks.append("未识别到明确入口文件，新人定位启动流程可能较慢。")
    return risks


def _rule_suggestions(architecture: dict[str, Any], score: float) -> list[str]:
    suggestions = []
    if score < 6:
        suggestions.append("目录结构信号较弱，建议明确 src、tests、docs、config 等职责边界。")
    if not architecture.get("entry_points"):
        suggestions.append("README 中建议标明主入口或启动命令。")
    suggestions.append("建议补充架构图、核心调用流程和模块职责说明，便于新人理解。")
    return suggestions


def _confidence_ratio(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(fallback or 0)
    if number > 1:
        number = number / 10 if number <= 10 else number / 100
    return round(max(0.0, min(1.0, number)), 2)


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [f"{key}: {_text(item)}" for key, item in value.items()]
    if isinstance(value, (list, tuple, set)):
        return [_text(item) for item in value if _text(item)]
    text = _text(value)
    return [text] if text else []


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value).strip()
