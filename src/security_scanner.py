from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .file_tree import IGNORED_DIRS
from .security_checker import check_security


SQL_CONCAT_RE = re.compile(r"(?i)(select|insert|update|delete).*(\+|format\(|%s|f['\"])")
BARE_EXCEPT_RE = re.compile(r"^\s*except\s*:\s*$")
HARDCODED_CONFIG_RE = re.compile(r"(?i)\b(host|port|database|db_url|url)\b\s*=\s*['\"][^'\"]+['\"]")


def scan_repository_risks(repo_path: Path, dependency_health: dict[str, Any] | None = None) -> dict[str, Any]:
    base = check_security(repo_path)
    extra = _scan_code_risk_patterns(Path(repo_path))
    risks = (base.get("risks") or []) + extra
    risk_counts = {
        "高": sum(1 for risk in risks if risk.get("severity") == "高"),
        "中": sum(1 for risk in risks if risk.get("severity") == "中"),
        "低": sum(1 for risk in risks if risk.get("severity") == "低"),
    }
    dep_score = (dependency_health or {}).get("score", 10)
    score = max(0, min(base.get("score", 100), round(dep_score * 10) - risk_counts["高"] * 8 - risk_counts["中"] * 4))
    return {
        **base,
        "score": score,
        "risks": risks[:120],
        "risk_counts": risk_counts,
        "summary": _summary(risk_counts),
        "rule_note": "未接入漏洞数据库和 SAST 引擎，当前为规则型风险扫描，不虚构具体 CVE。",
    }


def _scan_code_risk_patterns(repo_path: Path) -> list[dict[str, Any]]:
    risks = []
    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        for filename in filenames:
            path = Path(current_root) / filename
            if path.suffix.lower() not in {".py", ".js", ".ts", ".java", ".go", ".php"}:
                continue
            try:
                if path.stat().st_size > 800_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel_path = path.relative_to(repo_path).as_posix()
            for line_no, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if SQL_CONCAT_RE.search(stripped):
                    risks.append(_risk("中", "SQL 风险迹象", rel_path, line_no, "发现疑似 SQL 字符串拼接，建议使用参数化查询。", stripped))
                elif BARE_EXCEPT_RE.search(stripped):
                    risks.append(_risk("低", "异常处理", rel_path, line_no, "发现 bare except，可能隐藏真实异常。", stripped))
                elif HARDCODED_CONFIG_RE.search(stripped):
                    risks.append(_risk("低", "硬编码配置", rel_path, line_no, "发现疑似硬编码配置，建议改为环境变量或配置文件。", stripped))
                if len(risks) >= 60:
                    return risks
    return risks


def _risk(severity: str, category: str, path: str, line_no: int, message: str, line: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "path": f"{path}:{line_no}",
        "message": message,
        "evidence": line[:160],
    }


def _summary(counts: dict[str, int]) -> str:
    if not any(counts.values()):
        return "未发现明显安全、依赖或工程规范风险。"
    return f"规则扫描发现高风险 {counts['高']} 项、中风险 {counts['中']} 项、低风险 {counts['低']} 项。"
