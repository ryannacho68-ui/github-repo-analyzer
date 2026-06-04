from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import requests


DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_TAGS_ENDPOINT = "http://localhost:11434/api/tags"


def generate_report(
    analysis: dict,
    model: str = DEFAULT_MODEL,
    use_llm: bool = True,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: int = 90,
) -> dict:
    """Generate a Chinese Markdown report from deterministic analysis results."""
    compact_context = _compact_analysis(analysis)
    requested_model = model or DEFAULT_MODEL
    if not use_llm:
        return {
            "report": _template_report(compact_context),
            "mode": "template",
            "model": None,
            "message": "未启用 LLM，已生成模板报告。",
        }

    available_models = list_available_models(
        tags_endpoint=_tags_endpoint_from_generate_endpoint(endpoint),
        timeout=3,
    )
    if available_models and requested_model not in available_models:
        return {
            "report": _template_report(compact_context),
            "mode": "template",
            "model": None,
            "message": (
                f"Ollama 已运行，但未安装模型 {requested_model}。"
                f"当前可用模型：{', '.join(available_models)}。"
                f"请在页面选择可用模型，或运行：ollama pull {requested_model}"
            ),
        }

    prompt = _build_prompt(compact_context)
    try:
        response = requests.post(
            endpoint,
            json={
                "model": requested_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=timeout,
        )
        if response.status_code == 404:
            raise RuntimeError(
                f"Ollama API 返回 404，通常表示模型 {requested_model} 未安装。"
                f"可运行：ollama pull {requested_model}"
            )
        response.raise_for_status()
        data = response.json()
        report = (data.get("response") or "").strip()
        if not report:
            raise ValueError("Ollama returned an empty response.")
        return {
            "report": report,
            "mode": "ollama",
            "model": requested_model,
            "message": "已通过 Ollama 生成 AI 报告。",
        }
    except Exception as exc:
        return {
            "report": _template_report(compact_context),
            "mode": "template",
            "model": None,
            "message": f"Ollama 不可用，已退化为模板报告：{exc}",
        }


def list_available_models(
    tags_endpoint: str = DEFAULT_TAGS_ENDPOINT,
    timeout: int = 2,
) -> list[str]:
    """Return installed Ollama model names, or an empty list when unavailable."""
    try:
        response = requests.get(tags_endpoint, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    models = data.get("models") or []
    names = []
    for model in models:
        name = model.get("name") or model.get("model")
        if name:
            names.append(name)
    return sorted(set(names), key=str.lower)


def _tags_endpoint_from_generate_endpoint(endpoint: str) -> str:
    if endpoint.endswith("/api/generate"):
        return endpoint[: -len("/api/generate")] + "/api/tags"
    return DEFAULT_TAGS_ENDPOINT


def _build_prompt(context: dict[str, Any]) -> str:
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    return f"""
你是一个资深代码仓库分析顾问。请根据下面的“结构化静态分析结果”生成中文 Markdown 报告。

严格要求：
1. 只能依据这些结构化结果分析，不要假设你看过完整源码。
2. 不要输出空泛套话，要结合指标、风险和扣分原因。
3. 报告包含以下章节：项目概述、项目用途与目标用户、技术栈分析、架构分析、项目结构说明、代码规模、代码质量评价、文档完整性评价、安全与工程规范问题、Multi-Agent 协作摘要、新人上手建议、后续改进建议。
4. 语气适合课程设计答辩展示，清晰、专业、可执行。

结构化静态分析结果：
```json
{context_json}
```
""".strip()


def _compact_analysis(analysis: dict) -> dict:
    repo = analysis.get("repo_info", {})
    file_tree = analysis.get("file_tree", {})
    tech_stack = analysis.get("tech_stack", {})
    code_quality = analysis.get("code_quality", {})
    documentation = analysis.get("documentation", {})
    security = analysis.get("security", {})
    github_api = analysis.get("github_api", {})
    project_overview = analysis.get("project_overview", {})
    architecture = analysis.get("architecture", {})
    agents = analysis.get("agents", {})

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": {
            "owner": repo.get("owner"),
            "name": repo.get("name"),
            "url": repo.get("web_url"),
            "from_cache": repo.get("from_cache"),
        },
        "github_api": {
            "available": github_api.get("available"),
            "repo": github_api.get("repo", {}),
            "tree": github_api.get("tree", {}),
            "readme": {
                "available": (github_api.get("readme") or {}).get("available"),
                "path": (github_api.get("readme") or {}).get("path"),
                "excerpt": ((github_api.get("readme") or {}).get("excerpt") or "")[:1200],
            },
            "error": github_api.get("error"),
        },
        "project_overview": project_overview,
        "file_tree": {
            "total_files": file_tree.get("total_files"),
            "total_dirs": file_tree.get("total_dirs"),
            "total_size_kb": file_tree.get("total_size_kb"),
            "total_code_lines": file_tree.get("total_code_lines"),
            "language_line_counts": file_tree.get("language_line_counts"),
            "extension_counts": _limit_mapping(file_tree.get("extension_counts", {}), 20),
            "category_counts": file_tree.get("category_counts"),
            "category_ratios": file_tree.get("category_ratios"),
            "largest_files": (file_tree.get("largest_files") or [])[:8],
            "directory_summary": (file_tree.get("directory_summary") or [])[:8],
        },
        "tech_stack": {
            "main_language": tech_stack.get("main_language"),
            "languages": (tech_stack.get("languages") or [])[:10],
            "frameworks": tech_stack.get("frameworks"),
            "tools": tech_stack.get("tools"),
            "dependencies": {
                key: values[:30] for key, values in (tech_stack.get("dependencies") or {}).items()
            },
            "dependency_versions": {
                key: values[:30] for key, values in (tech_stack.get("dependency_versions") or {}).items()
            },
            "indicators": tech_stack.get("indicators"),
        },
        "architecture": architecture,
        "code_quality": {
            "score": code_quality.get("score"),
            "deductions": code_quality.get("deductions"),
            "python": {
                **(code_quality.get("python") or {}),
                "long_functions": (code_quality.get("python") or {}).get("long_functions", [])[:8],
                "parse_errors": (code_quality.get("python") or {}).get("parse_errors", [])[:8],
            },
            "long_files": (code_quality.get("long_files") or [])[:8],
            "todo_markers": (code_quality.get("todo_markers") or [])[:10],
            "tests": code_quality.get("tests"),
        },
        "documentation": documentation,
        "security": {
            "score": security.get("score"),
            "risk_counts": security.get("risk_counts"),
            "summary": security.get("summary"),
            "risks": (security.get("risks") or [])[:15],
        },
        "agents": {
            "summary": agents.get("summary", {}),
            "logs": [
                {
                    "agent": item.get("agent"),
                    "output": item.get("output"),
                    "elapsed_ms": item.get("elapsed_ms"),
                    "token_estimate": item.get("token_estimate"),
                }
                for item in (agents.get("logs") or [])[:6]
            ],
        },
    }


def _template_report(context: dict[str, Any]) -> str:
    repo = context["repo"]
    files = context["file_tree"]
    tech = context["tech_stack"]
    quality = context["code_quality"]
    docs = context["documentation"]
    security = context["security"]
    overview = context.get("project_overview") or {}
    architecture = context.get("architecture") or {}
    agents = context.get("agents") or {}

    frameworks = ", ".join(tech.get("frameworks") or []) or "未识别到明确框架"
    tools = ", ".join(tech.get("tools") or []) or "未识别到明确工程工具"
    deductions = "\n".join(f"- {item}" for item in quality.get("deductions") or [])
    doc_suggestions = "\n".join(f"- {item}" for item in docs.get("suggestions") or [])
    agent_findings = "\n".join(
        f"- {item}" for item in (agents.get("summary") or {}).get("key_findings", [])
    ) or "- Agent 输出较少，建议结合 Dashboard 中的结构化日志查看。"
    security_risks = security.get("risks") or []
    if security_risks:
        risk_lines = "\n".join(
            f"- [{risk['severity']}] {risk['path']}：{risk['message']}" for risk in security_risks[:10]
        )
    else:
        risk_lines = "- 未发现明显安全与工程规范风险。"

    return f"""# {repo.get("owner")}/{repo.get("name")} 仓库分析报告

## 1. 项目概述
项目类型：**{overview.get("project_type", "通用代码仓库")}**。

项目用途：{overview.get("purpose") or "暂未从 README 或仓库元信息中识别到明确用途。"}

目标用户：{overview.get("target_users", "需要理解或复用该仓库的开发者")}。本判断置信度约 {overview.get("confidence", 0)}/100。仓库共包含 {files.get("total_files", 0)} 个文件、{files.get("total_dirs", 0)} 个目录，总体大小约 {files.get("total_size_kb", 0)} KB。主要语言识别为 **{tech.get("main_language", "Unknown")}**。

## 2. 技术栈分析
- 主要语言：{tech.get("main_language", "Unknown")}
- 识别框架：{frameworks}
- 工程工具：{tools}
- 依据文件：{", ".join(tech.get("indicators") or []) or "未检测到典型依赖/工程配置文件"}

## 3. 架构分析
架构模式判断为：**{architecture.get("pattern", "Unknown")}**，置信度约 {round((architecture.get("confidence", 0) or 0) * 100)}%。入口文件：{", ".join(architecture.get("entry_points") or []) or "未识别到明确入口"}。

## 4. 项目结构说明
文件类别分布为：{json.dumps(files.get("category_counts") or {}, ensure_ascii=False)}。建议优先查看 README、依赖配置文件和文件数最多的核心目录。

## 5. 代码规模
仓库包含 {files.get("total_files", 0)} 个文件、{files.get("total_dirs", 0)} 个目录，代码行数约 {files.get("total_code_lines", 0)} 行。语言行数分布：{json.dumps(files.get("language_line_counts") or {}, ensure_ascii=False)}。

## 6. 代码质量评价
代码质量评分：**{quality.get("score", 0)}/100**。
{deductions}

Python 代码统计：{(quality.get("python") or {}).get("files", 0)} 个文件、{(quality.get("python") or {}).get("functions", 0)} 个函数、{(quality.get("python") or {}).get("classes", 0)} 个类，平均函数长度 {(quality.get("python") or {}).get("average_function_length", 0)} 行。

## 7. 文档完整性评价
文档完整性评分：**{docs.get("score", 0)}/100**。
{doc_suggestions}

## 8. 安全与工程规范问题
安全规范评分：**{security.get("score", 0)}/100**。{security.get("summary", "")}
{risk_lines}

## 9. Multi-Agent 协作摘要
{agent_findings}

## 10. 新人上手建议
- 先阅读 README 和依赖文件，确认安装与启动方式。
- 按主要语言和框架定位入口文件、核心模块与测试目录。
- 若测试缺失，建议先补充最小可运行测试，再进行功能修改。

## 11. 后续改进建议
- 补齐文档中的安装、运行、示例和许可证信息。
- 对超长函数、超长文件进行拆分，降低维护成本。
- 将敏感配置迁移到本地环境变量，并用示例配置文件说明字段含义。
"""


def _limit_mapping(mapping: dict, limit: int) -> dict:
    return dict(list(mapping.items())[:limit])
