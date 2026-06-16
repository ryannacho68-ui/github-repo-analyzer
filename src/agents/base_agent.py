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
        try:
            result = self.analyze(context, shared)
            status = result.status or "done"
            error_message = result.error_message or ""
        except Exception as exc:
            result = self.build_result(
                summary=f"{self.name} failed and returned a degraded result.",
                findings=[str(exc)],
                evidence=[{"type": "error", "detail": str(exc)}],
                score=0,
                suggestions=["检查 Agent 输入数据和工具调用，必要时查看 traceback。"],
                confidence="low",
                raw_output={"error": str(exc)},
                status="error",
                error_message=str(exc),
            )
            status = "error"
            error_message = str(exc)

        elapsed_seconds = round(time.perf_counter() - start, 3)
        result.elapsed_seconds = elapsed_seconds
        log = {
            "agent": result.agent_name,
            "agent_name": result.agent_name,
            "input": self.input_summary,
            "input_summary": self.input_summary,
            "tools_used": result.tools_used,
            "llm_used": result.llm_used,
            "model": _llm_meta(result).get("model"),
            "output_summary": result.summary,
            "evidence_count": len(result.evidence or []),
            "score": result.score,
            "output": result.to_dict(),
            "elapsed_ms": round(elapsed_seconds * 1000, 2),
            "elapsed_seconds": elapsed_seconds,
            "token_estimate": self._estimate_tokens(result.to_dict()),
            "status": status,
            "error_message": error_message,
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
        llm_used: bool = False,
        tools_used: list[str] | None = None,
        status: str = "done",
        error_message: str = "",
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
            llm_used=llm_used,
            tools_used=tools_used or [],
            status=status,
            error_message=error_message,
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


def _llm_meta(result: AgentResult) -> dict[str, Any]:
    raw = result.raw_output if isinstance(result.raw_output, dict) else {}
    meta = raw.get("_llm_meta") if isinstance(raw.get("_llm_meta"), dict) else {}
    return meta
