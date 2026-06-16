from __future__ import annotations

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
        architecture = analyze_architecture(context.local_path, file_tree, tech_stack)
        shared["architecture"] = architecture
        context.file_tree = file_tree

        modules = architecture.get("modules") or []
        score = round((architecture.get("confidence", 0) or 0) * 10, 1)
        evidence = [
            {"type": "entry_points", "paths": architecture.get("entry_points") or context.possible_entry_files},
            {"type": "directory_summary", "items": (file_tree.get("directory_summary") or [])[:12]},
            {"type": "rationale", "items": architecture.get("rationale") or []},
        ]
        findings = [
            f"结构模式判断为 {architecture.get('pattern', 'Unknown')}。",
            f"识别到 {len(modules)} 个主要模块/目录职责。",
            f"入口文件：{', '.join(architecture.get('entry_points') or ['未识别到明确入口'])}。",
        ]
        suggestions = []
        if score < 6:
            suggestions.append("目录结构信号较弱，建议明确 src、tests、docs、config 等职责边界。")
        if not architecture.get("entry_points"):
            suggestions.append("README 中建议标明主入口或启动命令。")
        return self.build_result(
            summary=f"{architecture.get('pattern', 'Unknown')}，置信度 {score}/10。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions or ["架构结构较清晰，可补充架构图和核心调用流程。"],
            confidence=score_to_confidence(score),
            raw_output=architecture,
            tools_used=["file_tree.py", "architecture_analyzer.py"],
        )
