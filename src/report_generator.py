from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


TEN_DIMENSIONS = [
    "项目概览",
    "技术栈识别",
    "架构分析",
    "代码规模",
    "代码质量",
    "文档完整性",
    "依赖健康度",
    "测试覆盖",
    "部署方式",
    "潜在问题",
]


def generate_repository_markdown(analysis: dict[str, Any]) -> str:
    repo = analysis.get("repo_info") or {}
    summary = analysis.get("final_summary") or {}
    scores = analysis.get("dimension_scores") or {}
    overview = analysis.get("project_overview") or {}
    tech = analysis.get("tech_stack") or {}
    architecture = analysis.get("architecture") or {}
    file_tree = analysis.get("file_tree") or {}
    quality = analysis.get("code_quality") or {}
    docs = analysis.get("documentation") or {}
    dependency = analysis.get("dependency_health") or {}
    test_deploy = analysis.get("test_deploy") or {}
    security = analysis.get("security") or {}

    return f"""# {repo.get('owner')}/{repo.get('name')} 仓库智能分析报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 总体评分

- 总体评分：{summary.get('overall_score', 0)}/10
- 仓库地址：{repo.get('web_url')}
- 项目类型：{overview.get('project_type', '不确定')}
- 项目用途：{overview.get('purpose', '不确定')}

| 分析维度 | 得分 |
|---|---:|
{_score_table(scores)}

## 2. 项目概览

- 解决问题/用途：{overview.get('purpose', '不确定')}
- 目标用户：{overview.get('target_users', '不确定')}
- 判断置信度：{overview.get('confidence', 0)}/100
- 证据：{_evidence_inline(overview.get('evidence') or [])}

## 3. 技术栈识别

- 主要语言：{tech.get('main_language', 'Unknown')}
- 框架/核心库：{', '.join(tech.get('frameworks') or ['未识别'])}
- 工程工具：{', '.join(tech.get('tools') or ['未识别'])}
- 依赖版本：{_dependency_versions(tech)}

## 4. 架构分析

- 架构模式：{architecture.get('pattern', 'Unknown')}
- 入口文件：{', '.join(architecture.get('entry_points') or ['未识别'])}
- 模块划分：{_module_lines(architecture.get('modules') or [])}
- 判断依据：{'; '.join(architecture.get('rationale') or ['证据不足'])}

## 5. 代码规模

- 文件总数：{file_tree.get('total_files', 0)}
- 目录总数：{file_tree.get('total_dirs', 0)}
- 总代码行数：{file_tree.get('total_code_lines', 0)}
- 语言行数：{json.dumps(file_tree.get('language_line_counts') or {}, ensure_ascii=False)}
- 测试文件数量：{((test_deploy.get('tests') or {}).get('test_file_count', 0))}
- 配置文件/部署文件线索：{len((analysis.get('context') or {}).get('config_files') or [])} / {len((analysis.get('context') or {}).get('deploy_files') or [])}

## 6. 代码质量

- 评分：{quality.get('score', 0)}/100
- 函数/类数量：{(quality.get('python') or {}).get('functions', 0)} / {(quality.get('python') or {}).get('classes', 0)}
- 平均函数长度：{(quality.get('python') or {}).get('average_function_length', 0)}
- 扣分原因：
{_bullet_lines(quality.get('deductions') or ['未发现明显代码质量扣分项。'])}

## 7. 文档完整性

- 评分：{docs.get('score', 0)}/100
- README：{'存在' if (docs.get('checks') or {}).get('readme_exists') else '缺失'}
- API 文档：{'有信号' if (docs.get('api_documentation') or {}).get('has_api_docs') else '未检测到'}
- 改进建议：
{_bullet_lines(docs.get('suggestions') or [])}

## 8. 依赖健康度

- 评分：{dependency.get('score', 0)}/10
- 依赖数量：{dependency.get('dependency_count', 0)}
- 固定版本/未固定版本：{dependency.get('pinned_count', 0)} / {dependency.get('unpinned_count', 0)}
- 说明：{dependency.get('limitations', '未接入漏洞数据库。')}

## 9. 测试覆盖

- 评分：{(test_deploy.get('tests') or {}).get('score', 0)}/10
- 测试文件数量：{(test_deploy.get('tests') or {}).get('test_file_count', 0)}
- 测试框架：{', '.join((test_deploy.get('tests') or {}).get('frameworks') or ['未识别'])}
- 说明：{(test_deploy.get('tests') or {}).get('coverage_note', '未运行覆盖率工具。')}

## 10. 部署方式

- 评分：{(test_deploy.get('deployment') or {}).get('score', 0)}/10
- Dockerfile：{_yes_no((test_deploy.get('deployment') or {}).get('dockerfile'))}
- docker-compose：{_yes_no((test_deploy.get('deployment') or {}).get('docker_compose'))}
- GitHub Actions：{_yes_no((test_deploy.get('deployment') or {}).get('github_actions'))}
- 环境变量示例：{', '.join((test_deploy.get('deployment') or {}).get('env_examples') or ['未检测到'])}

## 11. 潜在问题

- 安全/工程风险摘要：{security.get('summary', '未生成摘要')}
- 规则说明：{security.get('rule_note', '规则型扫描，不虚构 CVE。')}
{_risk_lines(security.get('risks') or [])}

## 12. 主要优点
{_bullet_lines(summary.get('strengths') or ['暂无明显优势。'])}

## 13. 主要问题
{_bullet_lines(summary.get('issues') or ['暂无明显问题。'])}

## 14. 改进建议
{_bullet_lines(summary.get('suggestions') or ['继续补充测试、文档和部署说明。'])}

## 15. Agent 协作日志摘要
{_agent_log_lines(analysis.get('agents', {}).get('logs') or [])}
"""


def generate_comparison_markdown(result: dict[str, Any]) -> str:
    comparison = result.get("comparison") or result
    repo_a = comparison.get("repo_a") or {}
    repo_b = comparison.get("repo_b") or {}
    return f"""# 仓库对比分析报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 对比对象

- 仓库 A：{repo_a.get('owner')}/{repo_a.get('name')}，{repo_a.get('url')}，项目类型：{repo_a.get('project_type')}
- 仓库 B：{repo_b.get('owner')}/{repo_b.get('name')}，{repo_b.get('url')}，项目类型：{repo_b.get('project_type')}

## 2. 总体结论

{comparison.get('overall_conclusion', '暂无总体结论。')}

## 3. 维度评分对比

| 分析维度 | 仓库 A 得分 | 仓库 B 得分 | 胜出方 | 简要原因 |
|---|---:|---:|---|---|
{_comparison_rows(comparison.get('dimension_comparison') or [])}

## 4. 技术栈对比

```json
{json.dumps(comparison.get('tech_stack_comparison') or {}, ensure_ascii=False, indent=2)}
```

## 5. 架构对比

```json
{json.dumps(comparison.get('architecture_comparison') or {}, ensure_ascii=False, indent=2)}
```

## 6. 代码质量对比

```json
{json.dumps(comparison.get('quality_comparison') or {}, ensure_ascii=False, indent=2)}
```

## 7. 文档、测试与部署对比

```json
{json.dumps(comparison.get('documentation_test_deploy_comparison') or {}, ensure_ascii=False, indent=2)}
```

## 8. 风险对比

```json
{json.dumps(comparison.get('risk_comparison') or {}, ensure_ascii=False, indent=2)}
```

## 9. 适用场景建议
{_dict_bullets(comparison.get('scenario_recommendations') or {})}

## 10. 改进建议

### 仓库 A
{_bullet_lines((comparison.get('suggestions') or {}).get('repo_a') or [])}

### 仓库 B
{_bullet_lines((comparison.get('suggestions') or {}).get('repo_b') or [])}

### 共同问题
{_bullet_lines((comparison.get('suggestions') or {}).get('common') or [])}
"""


def save_report_files(name: str, markdown: str, payload: dict[str, Any], outputs_dir: Path) -> dict[str, str]:
    outputs_dir = Path(outputs_dir)
    reports_dir = outputs_dir / "reports"
    json_dir = outputs_dir / "json"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "analysis")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = reports_dir / f"{safe}_{timestamp}.md"
    json_path = json_dir / f"{safe}_{timestamp}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path)}


def save_agent_logs(name: str, logs: list[dict[str, Any]], outputs_dir: Path) -> str:
    logs_dir = Path(outputs_dir) / "agent_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "agent_logs")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"{safe}_{timestamp}.json"
    path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _score_table(scores: dict[str, Any]) -> str:
    return "\n".join(f"| {dimension} | {score} |" for dimension, score in scores.items())


def _comparison_rows(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"| {row.get('分析维度')} | {row.get('仓库 A 得分')} | {row.get('仓库 B 得分')} | {row.get('胜出方')} | {row.get('简要原因')} |"
        for row in rows
    )


def _bullet_lines(items: list[Any]) -> str:
    return "\n".join(f"- {item}" for item in items if item) or "- 暂无。"


def _dict_bullets(items: dict[str, Any]) -> str:
    return "\n".join(f"- {key}: {value}" for key, value in items.items()) or "- 暂无。"


def _module_lines(modules: list[dict[str, Any]]) -> str:
    if not modules:
        return "未识别到明确模块。"
    return "；".join(f"{item.get('name')}：{item.get('role')}" for item in modules[:8])


def _evidence_inline(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "证据不足。"
    return "；".join(f"{item.get('source') or item.get('type')}: {item.get('text') or item.get('detail') or ''}" for item in evidence[:3])


def _dependency_versions(tech: dict[str, Any]) -> str:
    values = []
    for group, specs in (tech.get("dependency_versions") or {}).items():
        values.append(f"{group}: {', '.join(specs[:12])}")
    return "；".join(values) or "未识别到明确版本。"


def _risk_lines(risks: list[dict[str, Any]]) -> str:
    if not risks:
        return "- 未发现明显风险。"
    return "\n".join(f"- [{risk.get('severity')}] {risk.get('path')}：{risk.get('message')}" for risk in risks[:12])


def _agent_log_lines(logs: list[dict[str, Any]]) -> str:
    if not logs:
        return "- 暂无 Agent 日志。"
    return "\n".join(f"- {item.get('agent')}：{item.get('status')}，耗时 {item.get('elapsed_ms')} ms" for item in logs)


def _yes_no(value: Any) -> str:
    return "有" if value else "无"
