from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .file_tree import IGNORED_DIRS


TEST_FRAMEWORK_KEYWORDS = {
    "pytest": "pytest",
    "unittest": "unittest",
    "jest": "Jest",
    "mocha": "Mocha",
    "vitest": "Vitest",
    "junit": "JUnit",
}


def detect_tests(repo_path: Path, tech_stack: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    repo_path = Path(repo_path)
    test_files = []
    test_dirs = set()
    source_files = 0

    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        current_path = Path(current_root)
        if current_path.name.lower() in {"tests", "test", "__tests__"}:
            test_dirs.add(current_path.relative_to(repo_path).as_posix())
        for filename in filenames:
            path = current_path / filename
            suffix = path.suffix.lower()
            if suffix in {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs"}:
                source_files += 1
            lower = filename.lower()
            if lower.startswith("test_") or lower.endswith("_test.py") or ".test." in lower or ".spec." in lower:
                test_files.append(path.relative_to(repo_path).as_posix())

    frameworks = _detect_frameworks(tech_stack)
    ci_commands = _ci_test_commands(repo_path)
    ratio = round(len(test_files) / max(1, source_files) * 100, 2)
    score = 10.0
    suggestions = []
    if not test_files and not test_dirs:
        score -= 4
        suggestions.append("未检测到 tests/test 目录或测试文件，建议补充最小单元测试。")
    if not frameworks:
        score -= 1.5
        suggestions.append("未从依赖中识别到常见测试框架。")
    if not ci_commands:
        score -= 1.5
        suggestions.append("未在 CI 配置中检测到测试命令，建议将测试纳入自动化流程。")

    return {
        "score": round(max(0, score), 1),
        "has_tests": bool(test_files or test_dirs),
        "test_dirs": sorted(test_dirs),
        "test_files": sorted(test_files)[:200],
        "test_file_count": len(test_files),
        "source_file_count": source_files,
        "test_file_ratio": ratio,
        "frameworks": frameworks,
        "ci_test_commands": ci_commands,
        "coverage_note": "未运行覆盖率工具，仅基于测试文件结构、测试框架和 CI 命令进行估计。",
        "suggestions": suggestions or ["测试结构较明确，可进一步接入覆盖率统计。"],
    }


def _detect_frameworks(tech_stack: dict[str, Any]) -> list[str]:
    values = []
    for deps in (tech_stack.get("dependencies") or {}).values():
        values.extend(str(item).lower() for item in deps)
    values.extend(str(item).lower() for item in tech_stack.get("frameworks") or [])
    joined = " ".join(values)
    return sorted({label for keyword, label in TEST_FRAMEWORK_KEYWORDS.items() if keyword in joined})


def _ci_test_commands(repo_path: Path) -> list[str]:
    commands = []
    workflows = repo_path / ".github" / "workflows"
    if not workflows.exists():
        return commands
    for path in workflows.glob("*.y*ml"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if re.search(r"\b(pytest|npm test|yarn test|pnpm test|jest|go test|mvn test)\b", line):
                commands.append(f"{path.relative_to(repo_path).as_posix()}: {line.strip()[:140]}")
    return commands[:20]
