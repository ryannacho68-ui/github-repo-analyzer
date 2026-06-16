from __future__ import annotations

import json
from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..file_tree import analyze_file_tree
from ..tech_stack_detector import detect_tech_stack
from .base_agent import BaseAgent, score_to_confidence


class TechStackAgent(BaseAgent):
    name = "技术栈 Agent"
    input_summary = "tech_stack_detector.py + dependency files + import summary + file tree features"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        file_tree = shared.setdefault("file_tree", analyze_file_tree(context.local_path))
        rule_stack = detect_tech_stack(context.local_path, file_tree)
        context.file_tree = file_tree
        context.language_stats = file_tree.get("language_line_counts") or {}

        fallback_payload = _fallback_payload(context, rule_stack)
        client = shared.get("llm_client")
        if client:
            llm_payload = client.generate_json(
                system_prompt=(
                    "你是技术栈识别 Agent。你必须基于依赖文件、import 摘要、配置文件和文件结构证据输出 JSON。"
                    "不能编造数据库、框架或版本；无法判断时写“不确定”。"
                ),
                user_prompt=_tech_prompt(context, file_tree, rule_stack),
                fallback=fallback_payload,
            )
        else:
            llm_payload = {**fallback_payload, "_llm_meta": {"llm_used": False, "status": "no_client", "error_message": ""}}

        tech_stack = _normalize_tech_stack(llm_payload, rule_stack)
        shared["tech_stack"] = tech_stack
        meta = tech_stack.get("_llm_meta") or {}
        dependency_count = sum(len(values) for values in (tech_stack.get("dependencies") or {}).values())
        score = _score(tech_stack.get("score"), _rule_score(rule_stack))
        evidence = tech_stack.get("evidence") or _rule_evidence(context, rule_stack)
        findings = [
            f"主要语言：{tech_stack.get('main_language', 'Unknown')}",
            f"框架/核心库：{', '.join(tech_stack.get('frameworks') or ['不确定'])}",
            f"依赖数量约 {dependency_count} 个，包管理工具：{', '.join(tech_stack.get('package_manager') or tech_stack.get('tools') or ['不确定'])}",
        ]
        suggestions = tech_stack.get("suggestions") or [
            "在 README 中补充运行环境、关键依赖版本和技术栈选择理由。"
        ]
        return self.build_result(
            summary=f"{tech_stack.get('main_language', 'Unknown')} 技术栈，识别到 {len(tech_stack.get('frameworks') or [])} 个主要框架信号。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions,
            confidence=tech_stack.get("confidence") or score_to_confidence(score),
            raw_output=tech_stack,
            llm_used=bool(meta.get("llm_used")),
            tools_used=["tech_stack_detector.py", "file_tree.py", "Ollama generate_json"],
            status=meta.get("status", "done"),
            error_message=meta.get("error_message", ""),
        )


def _tech_prompt(context: RepositoryContext, file_tree: dict[str, Any], rule_stack: dict[str, Any]) -> str:
    dependency_excerpt = {
        path: content[:2500]
        for path, content in list((context.dependency_files or {}).items())[:12]
    }
    payload = {
        "repo_name": context.repo_name,
        "language_stats": context.language_stats or file_tree.get("language_line_counts") or {},
        "extension_counts": file_tree.get("extension_counts") or {},
        "dependency_file_paths": sorted((context.dependency_files or {}).keys()),
        "dependency_file_excerpts": dependency_excerpt,
        "import_summary": context.import_summary,
        "config_files": context.config_files[:80],
        "deploy_files": context.deploy_files[:60],
        "file_tree_excerpt": (file_tree.get("tree") or "")[:5000],
        "rule_stack": rule_stack,
        "required_json_fields": [
            "main_languages",
            "frameworks",
            "databases",
            "orm",
            "frontend_stack",
            "backend_stack",
            "ml_or_nlp_libraries",
            "testing_libraries",
            "deployment_tools",
            "key_dependencies",
            "dependency_versions",
            "package_manager",
            "evidence",
            "score",
            "confidence",
            "suggestions",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fallback_payload(context: RepositoryContext, rule_stack: dict[str, Any]) -> dict[str, Any]:
    return {
        "main_languages": [rule_stack.get("main_language", "Unknown")],
        "frameworks": rule_stack.get("frameworks") or [],
        "databases": ["不确定"],
        "orm": "不确定",
        "frontend_stack": [],
        "backend_stack": rule_stack.get("frameworks") or [],
        "ml_or_nlp_libraries": [item for item in rule_stack.get("frameworks", []) if item in {"PyTorch", "TensorFlow", "scikit-learn"}],
        "testing_libraries": [item for item in rule_stack.get("frameworks", []) if item in {"pytest", "jest", "mocha"}],
        "deployment_tools": [item for item in rule_stack.get("tools", []) if item in {"Docker", "Docker Compose", "GitHub Actions"}],
        "key_dependencies": rule_stack.get("dependencies") or {},
        "dependency_versions": rule_stack.get("dependency_versions") or {},
        "package_manager": rule_stack.get("tools") or [],
        "evidence": _rule_evidence(context, rule_stack),
        "score": _rule_score(rule_stack),
        "confidence": score_to_confidence(_rule_score(rule_stack)),
        "suggestions": ["技术栈来自规则识别；如需更准确语义解释，请启动 Ollama。"],
    }


def _normalize_tech_stack(payload: dict[str, Any], rule_stack: dict[str, Any]) -> dict[str, Any]:
    main_languages = _as_list(payload.get("main_languages")) or [rule_stack.get("main_language", "Unknown")]
    frameworks = _as_list(payload.get("frameworks")) or rule_stack.get("frameworks") or []
    tools = sorted(set(_as_list(payload.get("package_manager")) + _as_list(payload.get("deployment_tools")) + (rule_stack.get("tools") or [])))
    dependencies = rule_stack.get("dependencies") or {}
    key_dependencies = payload.get("key_dependencies") or dependencies
    return {
        "main_language": main_languages[0] if main_languages else rule_stack.get("main_language", "Unknown"),
        "main_languages": main_languages,
        "languages": rule_stack.get("languages") or [],
        "frameworks": frameworks,
        "databases": _as_list(payload.get("databases")) or ["不确定"],
        "orm": payload.get("orm") or "不确定",
        "frontend_stack": _as_list(payload.get("frontend_stack")),
        "backend_stack": _as_list(payload.get("backend_stack")),
        "ml_or_nlp_libraries": _as_list(payload.get("ml_or_nlp_libraries")),
        "testing_libraries": _as_list(payload.get("testing_libraries")),
        "deployment_tools": _as_list(payload.get("deployment_tools")),
        "dependencies": dependencies,
        "key_dependencies": key_dependencies,
        "dependency_versions": payload.get("dependency_versions") or rule_stack.get("dependency_versions") or {},
        "package_manager": _as_list(payload.get("package_manager")),
        "tools": tools,
        "indicators": rule_stack.get("indicators") or [],
        "evidence": payload.get("evidence") or [],
        "score": _score(payload.get("score"), _rule_score(rule_stack)),
        "confidence": payload.get("confidence") or score_to_confidence(_rule_score(rule_stack)),
        "suggestions": payload.get("suggestions") or [],
        "_llm_meta": payload.get("_llm_meta") or {},
    }


def _rule_evidence(context: RepositoryContext, rule_stack: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"type": "dependency_files", "paths": sorted(context.dependency_files.keys())},
        {"type": "import_summary", "top_imports": (context.import_summary.get("top_imports") or [])[:10]},
        {"type": "language_stats", "value": context.language_stats},
        {"type": "rule_indicators", "items": rule_stack.get("indicators") or []},
    ]


def _rule_score(rule_stack: dict[str, Any]) -> float:
    frameworks = rule_stack.get("frameworks") or []
    dependencies = rule_stack.get("dependencies") or {}
    score = 5 + min(2, len(frameworks) * 0.5) + (1.5 if dependencies else 0) + (1 if rule_stack.get("tools") else 0)
    return round(max(0, min(10, score)), 1)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items()]
    return [value]


def _score(value: Any, fallback: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = float(fallback or 0)
    if score > 10:
        score = score / 10
    return round(max(0.0, min(10.0, score)), 1)
