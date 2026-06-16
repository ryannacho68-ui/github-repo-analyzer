from __future__ import annotations

from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..file_tree import analyze_file_tree
from ..tech_stack_detector import detect_tech_stack
from .base_agent import BaseAgent, score_to_confidence


class TechStackAgent(BaseAgent):
    name = "技术栈 Agent"
    input_summary = "RepositoryContext.dependency_files + import_summary + file_tree"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        file_tree = shared.setdefault("file_tree", analyze_file_tree(context.local_path))
        tech_stack = detect_tech_stack(context.local_path, file_tree)
        shared["tech_stack"] = tech_stack
        context.file_tree = file_tree
        context.language_stats = file_tree.get("language_line_counts") or {}

        frameworks = tech_stack.get("frameworks") or []
        dependencies = tech_stack.get("dependencies") or {}
        dependency_count = sum(len(values) for values in dependencies.values())
        score = 5 + min(2, len(frameworks) * 0.5) + (1.5 if dependencies else 0) + (1 if tech_stack.get("tools") else 0)
        evidence = [
            {"type": "dependency_files", "paths": sorted(context.dependency_files.keys())},
            {"type": "import_summary", "top_imports": (context.import_summary.get("top_imports") or [])[:10]},
            {"type": "language_stats", "value": context.language_stats},
        ]
        findings = [
            f"主要语言识别为 {tech_stack.get('main_language', 'Unknown')}。",
            f"识别到框架/库：{', '.join(frameworks) if frameworks else '暂未识别到明确框架'}。",
            f"依赖数量约 {dependency_count} 个，工程工具：{', '.join(tech_stack.get('tools') or ['未识别'])}。",
        ]
        suggestions = []
        if not context.dependency_files:
            suggestions.append("补充标准依赖文件，提升环境复现能力。")
        if not frameworks:
            suggestions.append("如果项目依赖框架，建议在依赖文件或 README 中明确声明。")
        return self.build_result(
            summary=f"{tech_stack.get('main_language', 'Unknown')} 技术栈，{len(frameworks)} 个主要框架信号。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions or ["技术栈证据较清晰，可进一步补充版本约束和运行环境说明。"],
            confidence=score_to_confidence(score),
            raw_output=tech_stack,
        )
