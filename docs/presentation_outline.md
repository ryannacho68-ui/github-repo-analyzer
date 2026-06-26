# GitHub 仓库智能分析器答辩 PPT 大纲

## 1. 标题页

- GitHub 仓库智能分析器
- 静态分析 + LLM Agent 的仓库理解 Dashboard
- 小组成员 / 日期：留空

讲解重点：一句话说明系统作用：输入 GitHub URL，自动生成可解释的仓库分析报告。

## 2. 项目概述：做了什么

- 构建一个 Streamlit Web Dashboard
- 支持单仓库分析、双仓库对比、RAG 问答和报告导出
- 输出项目概览、技术栈、架构、质量、文档、测试、部署和风险
- 不直接把仓库交给 LLM，而是先做确定性静态分析

## 3. 项目背景：解决什么问题

- 陌生仓库理解成本高，需要同时阅读 README、目录、依赖、测试和部署
- 人工评估耗时，且不同人关注点不一致
- 直接让 LLM 总结链接容易缺少证据和准确统计
- 需要一个自动化、多维度、可追踪的仓库分析工具

## 4. 课程知识与项目对应

| 课程内容 | 项目体现 |
| --- | --- |
| 大模型基础 / Transformer | 使用 Ollama 调用 Qwen 本地模型 |
| Prompt Engineering | 限制 LLM 只能基于结构化证据输出 |
| RAG 架构 | 检索 README、配置和代码片段后回答问题 |
| Agent / 多智能体 | 多 Agent 分维度分析，Summary Agent 汇总 |
| 评估、优化与部署 | pytest、fallback、日志、报告导出和缓存处理 |

## 5. 系统架构图

放置图片：`docs/assets/system_architecture_flow.png`

讲解重点：
- GitHub API 获取元信息和 README
- git clone 提供本地源码
- RepositoryContext 统一传递证据
- Agent 只基于结构化证据分析

## 6. 模块划分

| 模块 | 文件 | 作用 |
| --- | --- | --- |
| 仓库获取 | `repo_loader.py`, `github_api_client.py` | API 获取、clone、缓存 |
| 上下文构建 | `context_builder.py`, `analysis_models.py` | README、依赖、源码样本 |
| 静态分析 | `file_tree.py`, `code_quality_analyzer.py` 等 | 指标和证据 |
| Agent 层 | `src/agents/*.py` | 分维度分析 |
| LLM / RAG | `llm_client.py`, `rag_qa.py` | Ollama 调用和问答 |
| Web 展示 | `app.py` | Dashboard、图表、导出 |

## 7. 关键技术实现 1：分析编排

代码片段：

```python
github_api = fetch_github_api_snapshot(repo_url)
repo_info = clone_or_use_cache(repo_url, base_dir, refresh=refresh).to_dict()
context = build_repository_context(repo_info, github_api)
```

原理说明：
- 先获取 GitHub API 信息
- 再获取本地代码
- 最后构建统一上下文，供所有 Agent 使用

## 8. 关键技术实现 2：Agent 结构化输出

代码片段：

```python
@dataclass
class AgentResult:
    agent_name: str
    summary: str
    findings: list[str]
    evidence: list[dict[str, Any]]
    score: float
    llm_used: bool = False
    tools_used: list[str] = field(default_factory=list)
```

原理说明：
- 每个 Agent 输出同一结构
- 记录证据、工具、评分和是否调用 LLM
- 前端和报告可以统一读取

## 9. 关键技术实现 3：Ollama 与降级

代码片段：

```python
if not self.enabled:
    self.last_call_log = {
        **base_log,
        "status": "disabled",
        "error_message": "LLM disabled by user option.",
    }
    return self._with_meta(fallback_payload, self.last_call_log)
```

原理说明：
- LLM 不可用时不终止分析
- fallback 保证模板报告可生成
- 日志记录失败原因，便于排查

## 10. 关键技术实现 4：RAG 问答

- 先检索 README、配置文件和源码片段
- 对“怎么运行”“模型类有哪些”等问题加入启发式规则
- Ollama 可用时只发送 Top-K 片段
- Ollama 不可用时返回基于片段的模板回答

建议放代码片段：`rag_qa.py` 中 AST 识别模型类的逻辑。

## 11. 实验结果：单仓库分析

示例仓库：`https://github.com/pallets/flask`

- Tech Stack、Architecture、Overview、Summary Agent 成功调用 Ollama
- Code Quality、Documentation、Test Deploy、Risk Agent 使用规则分析
- Dashboard 展示项目概览、技术栈、文件树、风险和评分
- Agent 日志记录 `llm_used`、`model`、`score`、`tools_used`

建议放截图：URL 输入区、分析进度、Agent 日志、文件树。

## 12. 实验结果：双仓库对比与测试

示例：Flask vs Starlette

- 分别执行两次单仓库分析
- Comparison Agent 输出十维度对比
- 页面展示雷达图、评分表、技术栈差异、架构差异和适用场景建议
- `pytest tests` 已知通过 15 个测试
- `pytest.ini` 避免扫描 `data/analyzed_repos` 下的第三方仓库

## 13. 遇到的问题与解决方案

| 问题 | 解决方案 |
| --- | --- |
| Ollama 不可用或模型不存在 | 自动 fallback 为模板报告 |
| GitHub API 403 限流 | API 失败后继续本地 clone 分析 |
| LLM 输出格式异常 | JSON 解析失败重试，前端做归一化 |
| pytest 误收集第三方测试 | `pytest.ini` 限定 `testpaths = tests` |
| 文件树和风险列表排版拥挤 | 改为滚动树形视图和三栏 Dashboard |
| Windows `.git` 文件权限问题 | 缓存复用和友好错误提示 |

## 14. 总结与未来改进

已完成：
- 单仓库分析、双仓库对比、RAG 问答
- 静态分析 + LLM Agent 混合架构
- Agent 日志、报告导出、Ollama 降级
- 真实仓库测试和自动化测试

未来改进：
- 接入 OSV、pip-audit、npm audit 等漏洞库
- 增加 coverage 和 lint 统计
- 扩展 JavaScript、Java、Go 等语言分析
- 使用 ChromaDB 做向量 RAG
- 增加 Docker 部署和历史报告管理

结束语：本项目把陌生仓库理解拆成可计算、可追踪、可展示的工程流程，而不是只做一次大模型文本总结。
