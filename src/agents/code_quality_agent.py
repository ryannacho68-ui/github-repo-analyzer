from __future__ import annotations

from typing import Any

from ..analysis_models import AgentResult, RepositoryContext
from ..code_quality_analyzer import analyze_code_quality
from .base_agent import BaseAgent, score_to_confidence


class CodeQualityAgent(BaseAgent):
    name = "代码质量 Agent"
    input_summary = "code_quality_analyzer.py + source samples + file scale metrics"

    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        quality = analyze_code_quality(context.local_path)
        shared["code_quality"] = quality
        py = quality.get("python") or {}
        quality["code_metrics"] = py
        quality["long_functions"] = py.get("long_functions") or []
        quality["large_files"] = quality.get("long_files") or []
        quality["complexity_summary"] = {
            "method": "基于 Python AST 统计函数长度，并结合 TODO 标记和长文件规则评估复杂度。",
            "average_function_length": py.get("average_function_length", 0),
            "long_function_count": len(py.get("long_functions") or []),
        }
        quality["naming_issues"] = []
        quality["todo_count"] = len(quality.get("todo_markers") or [])
        quality["exception_handling_summary"] = {
            "method": "扫描解析错误和异常处理风险信号，包括 bare except 等模式。",
            "parse_errors": py.get("parse_errors") or [],
        }
        score = round((quality.get("score", 0) or 0) / 10, 1)
        evidence = [
            {"type": "python_ast_metrics", "value": py},
            {"type": "long_files", "items": (quality.get("long_files") or [])[:8]},
            {"type": "todo_markers", "items": (quality.get("todo_markers") or [])[:8]},
            {"type": "source_samples", "items": context.source_samples[:5]},
        ]
        findings = [
            f"Python 函数 {py.get('functions', 0)} 个，类 {py.get('classes', 0)} 个，平均函数长度 {py.get('average_function_length', 0)} 行。",
            f"长函数数量：{len(py.get('long_functions') or [])}，超长文件数量：{len(quality.get('long_files') or [])}。",
            f"测试检测：{'存在测试' if (quality.get('tests') or {}).get('has_tests') else '未检测到测试'}。",
        ]
        suggestions = list(quality.get("deductions") or [])
        return self.build_result(
            summary=f"代码质量评分 {score}/10。",
            findings=findings,
            evidence=evidence,
            score=score,
            suggestions=suggestions or ["代码质量暂无明显扣分项，可继续补充复杂度和覆盖率检测。"],
            confidence=score_to_confidence(score),
            raw_output=quality,
            tools_used=["code_quality_analyzer.py", "Python ast"],
        )
