# GitHub 仓库智能分析器产品介绍大纲

## 1. 标题页

- GitHub 仓库智能分析器
- GitHub 仓库分析 Web 应用
- 小组成员：________
- 日期：________

讲解重点：一句话说明系统作用：输入 GitHub URL，自动生成结构化仓库分析 Dashboard。

## 2. 项目背景

- 陌生 GitHub 仓库理解成本高
- 人工评估需要同时看 README、目录、依赖、测试、部署和风险
- 直接让 LLM 总结链接容易缺少证据和准确统计
- 需要一个自动化、多维度、可解释的仓库分析工具

可放截图：GitHub 仓库主页和本系统首页对比。

## 3. 项目目标

- 输入一个 GitHub 仓库 URL，完成一键分析
- 输出 10 个维度的结构化分析报告
- 支持两个仓库横向对比
- 支持基于 README、配置和代码片段的 RAG 问答
- 支持 Agent 日志追踪和 Markdown / JSON 报告导出
- Ollama 不可用时仍能降级输出基础报告

## 4. 系统总体架构

- GitHub URL 输入
- GitHub API 获取元信息、README、远程文件树
- Repo Loader 克隆或读取缓存仓库
- Context Builder 构建 RepositoryContext
- 静态工具层提取证据
- 多 Agent 分析层生成结构化结果
- Summary Agent 汇总报告
- Streamlit Dashboard 展示和导出

可放图示：URL → Loader/API → Context → Tools → Agents → Dashboard。

## 5. 混合式 Agent 设计

- 规则工具负责事实和指标：文件数、目录数、依赖、AST、测试、部署、风险
- LLM Agent 负责语义解释：项目用途、技术栈理解、架构说明、最终总结和对比结论
- Overview / Tech Stack / Architecture / Summary / Comparison 调用 Ollama
- Code Quality / Documentation / Test Deploy / Risk 以规则分析为主
- LLM 只接收受控摘要和 JSON，不直接读取完整仓库

讲解重点：说明为什么不是“把仓库丢给大模型”。

## 6. 多 Agent 分工

| Agent | 输入 | 输出 | Ollama |
| --- | --- | --- | --- |
| Overview Agent | README、GitHub 元信息、文件结构 | 项目用途、目标用户、项目类型 | 是 |
| Tech Stack Agent | 依赖文件、import、配置 | 语言、框架、依赖版本、工具 | 是 |
| Architecture Agent | 文件树、入口、目录职责 | 架构模式、模块划分、设计风险 | 是 |
| Code Quality Agent | AST、长函数、TODO、测试线索 | 质量评分和扣分原因 | 否 |
| Documentation Agent | README、LICENSE、docs 信号 | 文档评分和建议 | 否 |
| Test Deploy Agent | tests、CI、Docker、脚本 | 测试部署成熟度 | 否 |
| Risk Agent | 依赖、敏感字符串、工程目录 | 风险列表和严重程度 | 否 |
| Summary Agent | 全部 AgentResult JSON | 最终报告和 10 维评分 | 是 |
| Comparison Agent | 两个仓库分析结果 | 横向对比和场景建议 | 是 |

## 7. 10 个分析维度

- 项目概览：用途、解决问题、目标用户
- 技术栈识别：语言、框架、依赖、工程工具
- 架构分析：结构模式、模块划分、入口文件
- 代码规模：文件数、目录数、代码行数、语言占比
- 代码质量：函数数量、平均长度、长函数、TODO、测试线索
- 文档完整性：README、安装、运行、示例、LICENSE、docs
- 依赖健康度：依赖数量、版本固定、依赖文件规范
- 测试覆盖：测试目录、测试文件、测试框架、CI 测试命令
- 部署方式：Docker、Compose、GitHub Actions、环境变量示例
- 潜在问题：敏感信息、硬编码、SQL 拼接、大文件、缓存目录

可放图示：雷达图或十维评分表截图。

## 8. Ollama 调用与结构化输出

- 本地模型：默认 `qwen2.5:7b`，日志中验证过 `qwen2.5-coder:7b`
- `llm_client.py` 封装 `/api/generate`
- `generate_json` 要求模型返回 JSON
- JSON 解析失败时重试，仍失败则使用 fallback
- 每次调用写入 `_llm_meta`
- Agent 日志展示 `llm_used`、model、status、prompt_length

可放截图：Multi-Agent 日志表格。

## 9. 单仓库分析流程

- 示例仓库：`https://github.com/pallets/flask`
- 输入 URL 后显示分析进度
- Dashboard 展示项目概览、技术栈、文件树、风险检测和评分
- 最新日志中 Tech Stack、Architecture、Overview、Summary 均成功调用 Ollama
- Code Quality、Documentation、Test Deploy、Risk 使用规则工具输出评分和证据

可放截图：
- URL 输入与进度条
- 项目概览区域
- 文件树与风险检测
- Agent 日志

## 10. 双仓库对比流程

- 示例：Flask vs Starlette
- 系统先分别执行单仓库分析
- Comparison Agent 生成 10 维度对比表
- 页面展示雷达图、评分表、技术栈差异、架构差异和适用场景建议
- 已处理 LLM 返回非标准结构导致前端报错的问题

可放截图：
- 双 URL 输入
- 对比雷达图
- 对比结论与建议

## 11. 测试与结果

- `python -m py_compile app.py` 和核心文件编译检查
- `pytest.ini` 限定只运行 `tests/`
- 测试覆盖 URL 解析、GitHub API 限流、缓存删除、质量分析、Agent、单仓库 smoke、双仓库 smoke
- 已知本地验证：`pytest tests` 通过 15 个测试
- Agent 日志显示 LLM Agent 与规则 Agent 均能正常输出
- 报告支持 Markdown / JSON 下载

讲解重点：测试不是证明分析绝对正确，而是证明主要流程和边界情况可运行。

## 12. 总结与改进

- 已完成：单仓库分析、双仓库对比、RAG 问答、Agent 日志、报告导出、Ollama 降级
- 项目特性：规则工具 + LLM Agent、结构化输出、可解释证据链、真实 Dashboard
- 当前局限：安全扫描可能误报，依赖漏洞未接入真实数据库，coverage 未真实运行，非 Python 质量分析较弱
- 后续优化：接入 OSV / pip-audit / npm audit，增加 coverage，扩展更多语言 AST，引入 JSON Schema，增加历史报告管理和向量 RAG

结束语：本系统把陌生仓库理解拆成可计算、可追踪、可展示的分析流程，而不是只做一次大模型文本总结。
