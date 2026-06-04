from __future__ import annotations

import os
import re
from pathlib import Path

from .file_tree import IGNORED_DIRS


RISKY_COMMITTED_DIRS = {
    "venv": "高",
    ".venv": "高",
    "env": "高",
    "ENV": "高",
    "site-packages": "高",
    "node_modules": "中",
    "__pycache__": "低",
    "dist": "低",
    "build": "低",
}

SENSITIVE_RULES = [
    ("GitHub token", re.compile(r"ghp_[A-Za-z0-9_]{20,}"), "高"),
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(token|access_token|auth_token|api[_-]?key|password|passwd|secret)\b\s*[:=]\s*['\"]?[^'\"\s]+"
        ),
        "中",
    ),
    ("private key header", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "高"),
]

TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".sh",
    ".ps1",
    ".env",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".xml",
}


def check_security(repo_path: Path) -> dict:
    repo_path = Path(repo_path)
    risks: list[dict] = []

    for current_root, dirnames, filenames in os.walk(repo_path):
        kept_dirs = []
        for dirname in dirnames:
            if dirname == ".git":
                continue
            if dirname in RISKY_COMMITTED_DIRS:
                risks.append(
                    {
                        "severity": RISKY_COMMITTED_DIRS[dirname],
                        "category": "工程规范",
                        "path": (Path(current_root) / dirname).relative_to(repo_path).as_posix(),
                        "message": f"疑似提交了 {dirname} 目录，应从仓库中移除并加入 .gitignore。",
                    }
                )
                continue
            if dirname in IGNORED_DIRS:
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in filenames:
            file_path = Path(current_root) / filename
            relative_path = file_path.relative_to(repo_path).as_posix()
            lower_name = filename.lower()

            if lower_name == ".env" or lower_name.startswith(".env."):
                severity = "低" if "example" in lower_name or "sample" in lower_name else "高"
                risks.append(
                    {
                        "severity": severity,
                        "category": "敏感文件",
                        "path": relative_path,
                        "message": ".env 类文件不应提交真实配置；示例文件也应避免包含真实凭据。",
                    }
                )

            try:
                size = file_path.stat().st_size
            except OSError:
                continue

            if size > 50 * 1024 * 1024:
                risks.append(
                    {
                        "severity": "高",
                        "category": "大文件",
                        "path": relative_path,
                        "message": "文件超过 50MB，建议改用对象存储、Git LFS 或下载脚本。",
                    }
                )
            elif size > 10 * 1024 * 1024:
                risks.append(
                    {
                        "severity": "中",
                        "category": "大文件",
                        "path": relative_path,
                        "message": "文件超过 10MB，会影响克隆速度和仓库维护。",
                    }
                )

            if _is_text_candidate(file_path, size):
                risks.extend(_scan_sensitive_strings(file_path, relative_path))

    risks = _deduplicate_risks(risks)
    counts = {
        "高": sum(1 for risk in risks if risk["severity"] == "高"),
        "中": sum(1 for risk in risks if risk["severity"] == "中"),
        "低": sum(1 for risk in risks if risk["severity"] == "低"),
    }
    score = max(0, 100 - counts["高"] * 20 - counts["中"] * 10 - counts["低"] * 3)

    return {
        "score": score,
        "risks": risks[:80],
        "risk_counts": counts,
        "summary": _summary_text(counts),
    }


def _scan_sensitive_strings(file_path: Path, relative_path: str) -> list[dict]:
    risks = []
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return risks

    for line_number, line in enumerate(text.splitlines(), start=1):
        if len(risks) >= 8:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#") and "pragma" not in stripped.lower():
            continue
        for label, pattern, severity in SENSITIVE_RULES:
            if not pattern.search(stripped):
                continue
            risks.append(
                {
                    "severity": severity,
                    "category": "敏感字符串",
                    "path": f"{relative_path}:{line_number}",
                    "message": f"发现疑似 {label}，请确认是否为真实凭据。",
                    "evidence": _mask_sensitive_line(stripped),
                }
            )
            break
    return risks


def _is_text_candidate(file_path: Path, size: int) -> bool:
    if size > 1_000_000:
        return False
    suffix = file_path.suffix.lower()
    return suffix in TEXT_EXTENSIONS or file_path.name.lower() in {"dockerfile", ".gitignore"}


def _mask_sensitive_line(line: str) -> str:
    line = re.sub(r"ghp_[A-Za-z0-9_]{8,}", "ghp_***", line)
    line = re.sub(
        r"(?i)(token|access_token|auth_token|api[_-]?key|password|passwd|secret)(\s*[:=]\s*)['\"]?[^'\"\s]+",
        r"\1\2***",
        line,
    )
    return line[:180]


def _deduplicate_risks(risks: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    severity_rank = {"高": 0, "中": 1, "低": 2}
    for risk in sorted(risks, key=lambda item: severity_rank.get(item["severity"], 9)):
        key = (risk.get("severity"), risk.get("category"), risk.get("path"), risk.get("message"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(risk)
    return unique


def _summary_text(counts: dict[str, int]) -> str:
    if not any(counts.values()):
        return "未发现明显敏感文件、凭据字符串或异常大文件。"
    return f"发现高风险 {counts['高']} 项、中风险 {counts['中']} 项、低风险 {counts['低']} 项。"

