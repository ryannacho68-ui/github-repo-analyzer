from __future__ import annotations

import json
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
        findings: Any,
        evidence: Any,
        score: float,
        suggestions: Any,
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
            findings=_text_list(findings, ["暂无明确发现。"]),
            evidence=_evidence_list(evidence),
            score=_bounded_score(score),
            suggestions=_text_list(suggestions, ["继续补充结构化证据后再细化判断。"]),
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


def _bounded_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return round(max(0.0, min(10.0, score)), 1)


def _text_list(value: Any, fallback: list[str]) -> list[str]:
    if value is None:
        return fallback
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else fallback
    if isinstance(value, dict):
        items = [f"{key}: {_short_json(item)}" for key, item in value.items()]
        return items or fallback
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = _short_json(item)
            else:
                text = str(item).strip()
            if text:
                items.append(text)
        return items or fallback
    text = str(value).strip()
    return [text] if text else fallback


def _evidence_list(value: Any) -> list[dict[str, Any]]:
    fallback = [{"type": "limitation", "detail": "证据不足，结论保持不确定。"}]
    if value is None:
        return fallback
    if isinstance(value, dict):
        if "type" in value or "source" in value:
            return [value]
        return [{"type": str(key), "value": item} for key, item in value.items()] or fallback
    if isinstance(value, (list, tuple, set)):
        items: list[dict[str, Any]] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, dict):
                items.append(item)
            else:
                items.append({"type": "note", "value": item})
        return items or fallback
    return [{"type": "note", "value": value}]


def _short_json(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = str(value)
    return text if len(text) <= 500 else f"{text[:497]}..."
