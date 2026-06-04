# 真实仓库分析展示与准确性评估

## 评估方法

本评估使用项目当前静态分析模块，对 5 个公开 GitHub 仓库执行一次无 LLM 的确定性分析。评估重点是技术栈、架构、代码规模、文档评分、安全规范和 Multi-Agent 日志是否有有效输出。

运行方式：

```bash
streamlit run app.py
```

也可以在页面中逐个输入下表仓库 URL，关闭或开启 Ollama 均可。Ollama 不可用时，系统会生成模板报告。

## 5 个真实仓库结果

| 仓库 | 文件数 | 代码行数 | 主要语言 | 框架/库 | 工具 | 架构判断 | 代码质量 | 文档评分 | 安全评分 | 风险项 | Agent 日志 |
| --- | ---: | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `octocat/Hello-World` | 1 | 0 | Unknown | 无 | 无 | 单体项目 / 通用工程结构 | 100 | 0 | 100 | 0 | 5 |
| `streamlit/streamlit-hello` | 11 | 433 | Python | NumPy / Streamlit / pandas | pip | 单体项目 / 通用工程结构 | 85 | 50 | 100 | 0 | 5 |
| `pypa/sampleproject` | 12 | 82 | Python | 无 | GitHub Actions / pyproject | 标准库式分层工程 | 100 | 75 | 90 | 1 | 5 |
| `pallets/itsdangerous` | 50 | 1745 | Python | 无 | GitHub Actions / mypy / pytest / ruff | 标准库式分层工程 | 97 | 45 | 80 | 2 | 5 |
| `pallets/click` | 150 | 26354 | Python | 无 | GitHub Actions / mypy / pytest / ruff | 标准库式分层工程 | 62 | 60 | 80 | 2 | 5 |

以上数据来自实际克隆后的本地静态分析。临时克隆目录在评估结束后已清理。

## 人工验证 vs 系统分析

| 仓库 | 人工验证结论 | 系统输出一致性 | 备注 |
| --- | --- | --- | --- |
| `octocat/Hello-World` | 极小 README 示例仓库，无明确技术栈 | 高 | 系统识别为 Unknown，合理 |
| `streamlit/streamlit-hello` | Streamlit 示例应用，Python 项目 | 高 | 成功识别 Python、Streamlit、pandas、NumPy |
| `pypa/sampleproject` | Python 打包示例，使用 pyproject 与 GitHub Actions | 高 | 成功识别 pyproject 和 GitHub Actions |
| `pallets/itsdangerous` | Python 库项目，使用 pytest/ruff/mypy/GitHub Actions | 中高 | 技术栈正确；文档评分偏低是因为 README 信息较少，文档集中在 docs/ |
| `pallets/click` | Python CLI 库，工程化程度较高 | 中 | 技术栈和工具正确；质量评分被长文件/长函数拉低，适合答辩说明启发式评分局限 |

## 10 个分析维度覆盖情况

| 维度 | 当前是否覆盖 | 实现方式 |
| --- | --- | --- |
| 项目概览 | 是 | GitHub API 描述 + README 摘要 + 包元信息 + 项目用途分析模块 + LLM/模板报告 |
| 技术栈识别 | 是 | 依赖文件、配置文件、后缀统计 |
| 架构分析 | 是 | 目录、入口文件、框架、Docker Compose 信号 |
| 代码规模 | 是 | 文件数、目录数、代码行数、语言行数分布 |
| 代码质量 | 是 | Python AST、长函数、长文件、TODO、测试 |
| 文档完整性 | 是 | README、安装、运行、示例、LICENSE、依赖文件、`.gitignore` |
| 依赖健康度 | 部分 | 识别依赖数量和版本；未联网检查过时版本和 CVE |
| 测试覆盖 | 部分 | 检测测试目录和测试文件；未计算覆盖率 |
| 部署方式 | 是 | Dockerfile、docker-compose、GitHub Actions |
| 潜在问题 | 是 | `.env`、凭据字符串、大文件、缓存目录、工程规范 |

## Agent 协作效率

当前 Multi-Agent 是确定性逻辑 Agent，不消耗真实 LLM token。系统仍会展示 token 估算，用于答辩说明如果替换成真实 LLM Agent 时的上下文规模。

| 指标 | 结果 |
| --- | --- |
| 每个仓库 Agent 数量 | 5 |
| 输出格式 | JSON |
| 记录内容 | Agent 名称、输入摘要、输出、耗时、token 估算、状态 |
| Dashboard 展示 | 支持表格展示与 JSON 展开 |

## RAG 问答质量评估建议

建议答辩前对任意一个仓库提 10 个问题，并人工评估回答是否准确：

1. 这个项目怎么在本地跑起来？
2. 入口文件在哪里？
3. 主要依赖有哪些？
4. 是否有 Docker 部署？
5. 是否有 GitHub Actions？
6. 测试文件在哪里？
7. 有没有数据库模型？
8. README 有没有安装步骤？
9. 代码中是否引用了环境变量？
10. 哪些文件最大或最值得先看？

当前 RAG 模块会返回检索来源，方便人工判断答案是否可追溯。

## 失败分析

| 仓库类型 | 可能问题 | 当前策略 |
| --- | --- | --- |
| 超大仓库 | 克隆慢、文件多、RAG 检索耗时 | 忽略大目录，限制大文件读取，建议后续异步任务 |
| 非主流语言 | AST 质量指标不足 | 仍输出结构、技术栈、文档、安全；后续增加语言解析器 |
| 文档集中在 docs/ | README 评分可能偏低 | 已在答辩中说明启发式评分局限 |
| 私有仓库 | 需要认证 | 当前默认公开仓库，不提交 token |
| 多仓库 monorepo | 架构判断可能过粗 | 后续增加 workspace/package 级别分析 |
