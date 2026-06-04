from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .file_tree import CODE_EXTENSIONS, IGNORED_DIRS


TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)


@dataclass
class FunctionMetric:
    name: str
    path: str
    start_line: int
    end_line: int
    length: int


class PythonAstVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.functions: list[FunctionMetric] = []
        self.class_count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_count += 1
        self.generic_visit(node)

    def _record_function(self, node: ast.AST) -> None:
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        self.functions.append(
            FunctionMetric(
                name=getattr(node, "name", "<anonymous>"),
                path=self.relative_path,
                start_line=start_line,
                end_line=end_line,
                length=max(1, end_line - start_line + 1),
            )
        )


def analyze_code_quality(repo_path: Path) -> dict:
    repo_path = Path(repo_path)
    python_files = _collect_files(repo_path, {".py"})
    code_files = _collect_files(repo_path, CODE_EXTENSIONS)
    long_files: list[dict] = []
    todo_markers: list[dict] = []
    parse_errors: list[dict] = []
    all_functions: list[FunctionMetric] = []
    class_count = 0
    total_python_lines = 0

    test_info = _detect_tests(repo_path)

    for file_path in python_files:
        relative_path = file_path.relative_to(repo_path).as_posix()
        source = _read_text(file_path)
        line_count = source.count("\n") + (1 if source else 0)
        total_python_lines += line_count
        if line_count > 500:
            long_files.append({"path": relative_path, "lines": line_count})

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            parse_errors.append(
                {
                    "path": relative_path,
                    "line": exc.lineno or 0,
                    "message": exc.msg,
                }
            )
            continue

        visitor = PythonAstVisitor(relative_path)
        visitor.visit(tree)
        all_functions.extend(visitor.functions)
        class_count += visitor.class_count

    for file_path in code_files:
        relative_path = file_path.relative_to(repo_path).as_posix()
        text = _read_text(file_path)
        if not text:
            continue
        line_count = text.count("\n") + 1
        if file_path.suffix.lower() != ".py" and line_count > 500:
            long_files.append({"path": relative_path, "lines": line_count})
        todo_markers.extend(_find_todo_markers(text, relative_path))

    long_functions = [
        metric.__dict__ for metric in all_functions if metric.length > 80
    ]
    average_function_length = (
        round(sum(metric.length for metric in all_functions) / len(all_functions), 2)
        if all_functions
        else 0
    )

    score, deductions = _score_quality(
        python_files_count=len(python_files),
        average_function_length=average_function_length,
        long_functions_count=len(long_functions),
        long_files_count=len(long_files),
        todo_count=len(todo_markers),
        parse_errors_count=len(parse_errors),
        has_tests=test_info["has_tests"],
    )

    return {
        "score": score,
        "deductions": deductions,
        "python": {
            "files": len(python_files),
            "lines": total_python_lines,
            "functions": len(all_functions),
            "classes": class_count,
            "average_function_length": average_function_length,
            "long_functions": long_functions[:30],
            "parse_errors": parse_errors[:30],
        },
        "long_files": sorted(long_files, key=lambda item: item["lines"], reverse=True)[:30],
        "todo_markers": todo_markers[:50],
        "tests": test_info,
    }


def _collect_files(repo_path: Path, extensions: set[str]) -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        for filename in filenames:
            path = Path(current_root) / filename
            if path.suffix.lower() in extensions:
                files.append(path)
    return files


def _detect_tests(repo_path: Path) -> dict:
    test_dirs = []
    test_files = []
    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        current_path = Path(current_root)
        if current_path.name.lower() in {"tests", "test"}:
            test_dirs.append(current_path.relative_to(repo_path).as_posix())
        for filename in filenames:
            lower_name = filename.lower()
            if lower_name.startswith("test_") and lower_name.endswith(".py"):
                test_files.append((current_path / filename).relative_to(repo_path).as_posix())
            elif lower_name.endswith("_test.py"):
                test_files.append((current_path / filename).relative_to(repo_path).as_posix())
    return {
        "has_tests": bool(test_dirs or test_files),
        "test_dirs": sorted(set(test_dirs))[:20],
        "test_files": sorted(set(test_files))[:30],
    }


def _find_todo_markers(text: str, relative_path: str) -> list[dict]:
    markers: list[dict] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = TODO_RE.search(line)
        if not match:
            continue
        markers.append(
            {
                "path": relative_path,
                "line": line_number,
                "tag": match.group(1).upper(),
                "content": line.strip()[:160],
            }
        )
        if len(markers) >= 20:
            break
    return markers


def _score_quality(
    python_files_count: int,
    average_function_length: float,
    long_functions_count: int,
    long_files_count: int,
    todo_count: int,
    parse_errors_count: int,
    has_tests: bool,
) -> tuple[int, list[str]]:
    score = 100
    deductions: list[str] = []

    if python_files_count and not has_tests:
        deduction = 15
        score -= deduction
        deductions.append(f"未检测到 Python 测试目录或 test_*.py，扣 {deduction} 分。")
    if parse_errors_count:
        deduction = min(12, parse_errors_count * 4)
        score -= deduction
        deductions.append(f"存在 {parse_errors_count} 个 Python AST 解析失败文件，扣 {deduction} 分。")
    if long_functions_count:
        deduction = min(20, long_functions_count * 2)
        score -= deduction
        deductions.append(f"存在 {long_functions_count} 个超过 80 行的函数，扣 {deduction} 分。")
    if long_files_count:
        deduction = min(15, long_files_count * 3)
        score -= deduction
        deductions.append(f"存在 {long_files_count} 个超过 500 行的文件，扣 {deduction} 分。")
    if average_function_length > 50:
        score -= 10
        deductions.append("平均函数长度超过 50 行，扣 10 分。")
    elif average_function_length > 35:
        score -= 5
        deductions.append("平均函数长度超过 35 行，扣 5 分。")
    if todo_count:
        deduction = min(10, todo_count)
        score -= deduction
        deductions.append(f"发现 {todo_count} 个 TODO/FIXME/HACK 标记，扣 {deduction} 分。")

    if not deductions:
        deductions.append("未发现明显代码质量扣分项。")

    return max(0, score), deductions


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 1_500_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""

