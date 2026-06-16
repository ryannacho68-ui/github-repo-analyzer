from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from ..analysis_models import AgentResult, RepositoryContext


class BaseAgent(ABC):
    name = "Base Agent"
    input_summary = "RepositoryContext + shared analysis facts"

    def run(self, context: RepositoryContext, shared: dict[str, Any]) -> tuple[AgentResult, dict[str, Any]]:
        start = time.perf_counter()
        result = self.analyze(context, shared)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        log = {
            "agent": result.agent_name,
            "input": self.input_summary,
            "output": result.to_dict(),
            "elapsed_ms": elapsed_ms,
            "token_estimate": self._estimate_tokens(result.to_dict()),
            "status": "done",
        }
        return result, log

    @abstractmethod
    def analyze(self, context: RepositoryContext, shared: dict[str, Any]) -> AgentResult:
        raise NotImplementedError

    def build_result(
        self,
        summary: str,
        findings: list[str],
        evidence: list[dict[str, Any]],
        score: float,
        suggestions: list[str],
        confidence: str = "medium",
        raw_output: dict[str, Any] | None = None,
    ) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            summary=summary,
            findings=findings or ["暂无明确发现。"],
            evidence=evidence or [{"type": "limitation", "detail": "证据不足，结论保持不确定。"}],
            score=round(max(0.0, min(10.0, float(score))), 1),
            suggestions=suggestions or ["继续补充结构化证据后再细化判断。"],
            confidence=confidence,
            raw_output=raw_output or {},
        )

    @staticmethod
    def _estimate_tokens(payload: dict[str, Any]) -> int:
        return max(1, round(len(str(payload)) / 4))


def score_to_confidence(score: float) -> str:
    if score >= 8:
        return "high"
    if score >= 5:
        return "medium"
    return "low"
