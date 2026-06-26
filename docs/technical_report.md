# GitHub 仓库智能分析器技术报告

## 一、选题背景与目标

在实际开发中，理解一个陌生 GitHub 仓库往往需要同时查看 README、目录结构、依赖文件、入口文件、测试目录、部署配置和安全风险。对于小型项目，人工阅读还能接受；一旦仓库文件较多，判断项目用途、技术栈和维护质量就会变得比较费时。另一方面，如果只是把仓库链接或少量代码直接交给大模型总结，模型很难准确统计文件数量、函数长度、依赖版本和测试情况，也容易生成缺少证据的结论。

本项目围绕“GitHub 仓库智能分析器”实现一个可本地运行的 Streamlit Web 应用。用户输入 GitHub 仓库 URL 后，系统自动获取仓库信息并克隆代码，从项目概览、技术栈、架构、代码规模、代码质量、文档完整性、依赖健康度、测试覆盖、部署方式和潜在问题十个维度生成分析报告。项目的重点不是封装一个聊天接口，而是先用 Python 程序做确定性静态分析，再把结构化结果交给多 Agent 和本地大模型进行解释、汇总与展示。

项目最终希望解决三个问题：第一，帮助开发者快速判断一个仓库是做什么的、是否值得继续阅读；第二，用可复现的指标辅助评估代码质量、文档和工程规范；第三，通过 Agent 日志、RAG 问答和双仓库对比，使分析过程更透明，也更接近真实代码分析产品。

从工程实践角度看，这个项目把多个能力组合到一个完整系统里。仓库获取体现了 API 调用和异常处理，静态分析体现了程序化特征提取，Prompt 设计体现了对模型输入边界的控制，多 Agent 架构体现了复杂任务拆分，RAG 问答体现了检索增强思想，Dashboard 和报告导出则体现了工程交付能力。相比只做一个脚本，本项目更强调从输入、分析、展示到导出的完整闭环。

## 二、相关技术介绍

系统同时使用 GitHub API 和 git clone。GitHub API 负责获取仓库描述、默认分支、stars、forks、license、topics、README 摘要和远程文件树，这些信息适合在分析开始时建立项目背景。git clone 负责下载本地仓库，便于后续进行文件遍历、AST 解析、依赖读取、安全扫描和 RAG 检索。未配置 GitHub token 时，API 可能触发限流，系统会显示友好提示，并继续使用本地 clone 完成静态分析。

Ollama 用于本地大模型调用。项目默认模型为 `qwen2.5:7b`，页面中也可以选择本机已有模型；实际日志中使用过 `qwen2.5-coder:7b`。`llm_client.py` 封装 `/api/generate`，提供 `generate_json` 和 `generate_text`，并记录 `llm_used`、model、prompt_length、status 和 error_message。Prompt 设计要求模型只根据结构化输入回答，不能声称读过完整仓库，也不能编造漏洞编号、覆盖率或不存在的技术栈。

多 Agent 分工是本项目的核心组织方式。每个 Agent 都输出统一的 `AgentResult`，包含 summary、findings、evidence、score、suggestions、confidence、tools_used、llm_used 和 status。这样前端可以展示每个结论来自哪个工具、是否调用了 LLM、证据数量是多少，也方便后续扩展新的 Agent。

静态分析保证了指标的可解释性。`file_tree.py` 统计文件数、目录数、文件类型比例、最大文件、目录规模和语言行数；`code_quality_analyzer.py` 使用 Python AST 统计函数、类、平均函数长度、超长函数和语法解析错误；文档、部署、依赖和风险检查也都由规则工具完成。RAG 问答模块则先检索 README、配置和代码片段，再在可选情况下调用 Ollama 回答问题，避免把整个仓库直接放进上下文。

结构化 JSON 输出是连接规则工具和 LLM 的关键。规则工具输出字典和列表，Agent 再把这些数据转换为统一字段，最后 Summary Agent 和 Comparison Agent 才生成面向用户的自然语言报告。这样做虽然比直接调用一次模型更复杂，但能够保留证据链，也方便页面把同一份结果展示为表格、图表、日志和 Markdown 报告。

前端使用 Streamlit 实现 Dashboard。页面包含 URL 输入、分析按钮、进度条、指标卡、文件类型图表、质量雷达图、文件树、风险列表、Agent 日志、RAG 问答和报告下载。布局采用深色三栏风格，使结果更像一个代码分析工具，而不是命令行文本的简单搬运。

## 三、系统需求分析

系统需要完成的第一类功能是单仓库分析。用户输入 GitHub URL 后，系统自动解析 owner/repo，获取 API 快照，克隆或读取缓存仓库，构建 `RepositoryContext`，再运行多个 Agent 输出十个维度的分析结果。每个维度都要求有有效输出，不能只给空泛描述。

第二类功能是双仓库对比。用户输入两个仓库后，系统分别执行单仓库分析，然后由 Comparison Agent 横向比较维度评分、技术栈、架构、质量、文档、测试部署和风险，并给出学习、二次开发和生产部署等场景建议。

第三类功能是可追踪性和导出。系统需要记录 Agent 日志，展示每个 Agent 的输入摘要、使用工具、是否调用 Ollama、状态、耗时和输出摘要。分析结果支持 Markdown 和 JSON 下载，运行产物保存到 `outputs/reports/`、`outputs/json/` 和 `outputs/agent_logs/`，这些目录默认被 `.gitignore` 忽略。

第四类功能是 RAG 问答和降级处理。完成单仓库分析后，用户可以继续提问“怎么运行”“数据库模型有哪些”“入口文件在哪里”等问题。若 Ollama 不可用，系统仍需返回基于检索片段和规则模板的回答；若 GitHub API 限流或模型缺失，核心静态分析仍应可用。

## 四、系统总体设计

系统主流程为：GitHub URL 输入，`github_api_client.py` 获取 API 快照，`repo_loader.py` 克隆或读取缓存，`context_builder.py` 构建 `RepositoryContext`，静态工具提取事实，多 Agent 分维度分析，Summary Agent 汇总报告，最后由 Streamlit Dashboard 展示和导出。

`RepositoryContext` 是连接各模块的核心数据结构，字段包括仓库名称、owner、URL、本地路径、README 文本与摘要、依赖文件、源代码样本、测试文件、配置文件、部署文件、语言统计、import 摘要和入口候选文件。这样各 Agent 不需要重复扫描仓库，只需基于上下文和共享结果完成自己的分析任务。

项目采用“规则工具 + LLM Agent”的混合架构。规则工具负责提取事实和指标，例如文件数量、依赖列表、AST 指标、README 检查项、Docker 配置和风险信号；Agent 负责基于证据做判断、评分和建议。Overview、Tech Stack、Architecture、Summary 和 Comparison Agent 会调用 Ollama；Code Quality、Documentation、Test Deploy 和 Risk Agent 主要使用规则分析。这个设计保留了 LLM 的语言理解能力，也避免让模型承担精确统计和安全扫描这类更适合程序完成的任务。

这种设计也体现了一个取舍：系统没有追求让每个 Agent 都变成真正的独立模型调用。对于代码质量、测试部署和风险扫描，规则更稳定，结果也更容易解释；对于项目用途、技术栈语义和最终报告，LLM 更适合把碎片化证据组织成可读结论。因此，本项目把 LLM 放在需要语义理解和表达的环节，把规则工具放在需要准确统计和可复现判断的环节。

## 五、关键模块实现

仓库加载模块 `repo_loader.py` 输入 GitHub URL，支持 HTTPS 和 SSH 地址解析，生成安全目录名，判断使用缓存还是重新克隆，并通过 `git clone --depth 1` 获取代码。它对无效 URL、git 未安装、超时、克隆失败和 Windows 下只读 `.git` pack 文件删除失败都做了错误处理。

上下文构建模块 `context_builder.py` 输入仓库本地路径和 API 快照，遍历文件时忽略 `.git`、venv、node_modules、__pycache__、dist、build 等目录。它读取 README、依赖文件、配置文件、测试文件、部署文件和源代码样本，并用 AST 统计 Python import，最终输出 `RepositoryContext`。

Ollama 调用模块 `llm_client.py` 提供统一模型接口。`generate_json` 会检查可用模型、发送 prompt、解析 JSON，并在解析失败时重试一次；如果模型不可用，则返回 fallback。所有模型调用结果都会附带 `_llm_meta`，用于 Dashboard 和日志展示。

Overview Agent 负责判断项目用途。它先调用 `project_overview_analyzer.py` 从 GitHub description、README、topics、pyproject 或 package.json 中提取证据，再让 Ollama 基于受控输入输出项目类型、解决问题、目标用户、核心功能和建议。

Tech Stack Agent 调用 `file_tree.py` 和 `tech_stack_detector.py`。规则层根据 requirements、pyproject、setup.py、package.json、pom.xml、build.gradle、Dockerfile 和 `.github/workflows` 识别语言、框架、依赖版本和工程工具，LLM 层再解释技术栈组成。

Architecture Agent 调用 `architecture_analyzer.py`，根据顶层目录、入口文件、框架和 Docker Compose 信号判断 MVC、组件化前端、多服务候选、标准库式分层工程或通用工程结构。Ollama 在规则结果基础上补充架构说明、模块职责、判断依据和设计风险。

Code Quality Agent 使用 `code_quality_analyzer.py`。它通过 Python AST 统计函数数量、类数量、平均函数长度、超过 80 行的函数、超过 500 行的文件、TODO/FIXME/HACK 标记和测试线索，并输出代码质量评分及扣分原因。

Documentation Agent 使用 `doc_checker.py`，检查 README、项目介绍、安装方法、运行方式、使用示例、LICENSE、依赖文件和 `.gitignore`，并结合 README 或文档路径判断 API 文档信号。Test Deploy Agent 使用 `test_detector.py` 和 `deploy_detector.py` 检查测试目录、测试框架、CI 测试命令、Docker、Compose、GitHub Actions、环境变量示例和启动脚本。

Risk Agent 调用 `dependency_checker.py` 和 `security_scanner.py`。依赖健康度当前主要检查依赖数量、版本固定情况和依赖文件规范性；风险扫描检查 `.env`、虚拟环境目录、node_modules、site-packages、敏感字符串、大文件、SQL 字符串拼接、bare except 和硬编码配置，并按高、中、低标注。

Summary Agent 汇总全部 AgentResult，生成十维度评分和最终报告。Comparison Agent 用于双仓库场景，先用规则生成维度对比表，再调用 Ollama 形成综合结论。RAG 模块 `rag_qa.py` 根据问题检索 README、配置和代码片段，对运行步骤和模型类等常见问题还加入了启发式分析。`app.py` 负责 Streamlit 页面展示，包括分析进度、图表、文件树、风险列表、Agent 日志、问答和报告导出。

这些模块之间通过共享字典传递中间结果，例如技术栈分析结果会被 Architecture Agent、Risk Agent 和 Summary Agent 继续使用；文件树结果既用于页面展示，也用于架构判断和代码规模评分。为了避免重复扫描仓库，Orchestrator 会按照固定顺序执行 Agent，并把每一步结果写回 shared。这样既减少了重复工作，也让日志顺序与页面进度保持一致。

## 六、验证与功能检查

项目本地保存了 Flask 仓库分析日志 `outputs/agent_logs/pallets_flask_20260616_222914.json`。该日志显示 Tech Stack、Architecture、Overview 和 Summary Agent 均成功调用 `qwen2.5-coder:7b`，状态为 ok；Code Quality、Documentation、Test Deploy 和 Risk Agent 使用规则分析，状态为 done。日志中记录的分数包括技术栈 8.5、架构 6.4、项目概览 8.9、代码质量 5.6、文档 6.0、测试部署 5.8、风险 4.0、汇总 6.5，说明 LLM Agent 和规则 Agent 都有实际输出。

双仓库对比日志为 `outputs/agent_logs/compare_flask_starlette_20260616_223408.json`。日志包含 Flask 与 Starlette 两次单仓库分析，以及最后的 Comparison Agent。Comparison Agent 的 `llm_used` 为 true，模型为 `qwen2.5-coder:7b`，证据数量为 10，对应十个维度的横向比较。项目曾出现 LLM 返回字符串列表导致前端雷达图报错的问题，后续已在 Comparison Agent 和前端增加归一化处理，避免非标准模型输出破坏页面。

测试方面，项目包含 URL 解析、GitHub API token 与限流处理、Windows 缓存删除、代码质量测试识别、十维度契约、Summary Agent、Architecture Agent、Comparison Agent 容错、单仓库 smoke 和双仓库 smoke 等测试。`pytest.ini` 将测试范围限制为 `tests/`，避免扫描 `data/analyzed_repos/` 中缓存的第三方仓库。最近一次已知验证为 `pytest tests` 通过 15 个测试，最终提交前仍以本机最新运行为准。

前端功能也进行了验证。页面点击开始分析后按钮会变灰并显示分析中，完成后恢复；项目类型和结构模式支持横向滚动；文件树改为可滚动树形浏览；风险检测只保留单向滚动；三栏内容长度更均衡。整体页面能够展示项目概览、技术栈、文件结构、质量评分、风险、Agent 日志、AI 报告和导出按钮。

除 Flask 和 Starlette 之外，项目文档中还保留了对多个公开仓库的分析记录，例如 `octocat/Hello-World`、`streamlit/streamlit-hello`、`pypa/sampleproject`、`pallets/itsdangerous` 和 `pallets/click`。这些仓库规模和类型差异较大，可以用于观察规则分析的适用边界。对于非常小的仓库，系统会给出较少的技术栈和架构信号；对于文档集中在 `docs/` 的库项目，README 评分可能偏低，需要在结果分析中说明启发式评分的限制。

实际走查时，可以先查看单仓库分析流程，再查看 Agent 日志和 RAG 问答，最后切换到双仓库对比。这样的顺序能够说明系统不是一次性生成文本，而是经历了仓库获取、上下文构建、工具分析、Agent 分析和 Summary 汇总等步骤。页面中的进度条、按钮状态和日志表格也能直观看出每个阶段已经执行。

## 七、结果分析

从实现效果看，项目的优势在于分工清楚和证据可追踪。静态工具负责可复现的事实，Agent 负责解释和评分，Summary Agent 只汇总已有结果，不重新编造细节。日志中的 `tools_used`、`llm_used`、status 和 evidence_count 让用户可以判断每个结论的来源。

结构化输出也增强了系统的可维护性。`RepositoryContext`、`AgentResult` 和 `ComparisonResult` 让不同模块的输入输出保持一致，前端、报告生成和测试都可以围绕这些结构工作。双仓库对比、RAG 问答和报告导出让工具不只停留在单次分析，而是具备一定产品化形态。

项目仍有局限。LLM 输出可能误判，因此需要 fallback 和结果归一化。安全扫描是轻量规则检查，可能误报，也没有接入 CVE、OSV、pip-audit 或 npm audit。依赖健康度当前只做结构性判断，不能说明依赖是否过时。测试覆盖只是根据测试文件和 CI 信号估计，没有运行 coverage。RAG 问答依赖代码切分和关键词检索，遇到超大仓库、非主流语言或复杂 monorepo 时效果可能下降。非 Python 语言的代码质量分析也还不够细。

另一个需要注意的地方是评分并不等同于绝对质量判断。当前分数更多是基于结构信号的启发式结果，例如缺少 Dockerfile 会影响部署评分，长文件和长函数会影响代码质量评分，README 缺少安装运行说明会影响文档评分。这些规则适合帮助用户定位问题，但不能替代人工 code review，也不能代表项目在业务场景中的真实价值。

## 八、总结与改进方向

本项目完成了一个可运行的 GitHub 仓库智能分析 Dashboard，支持单仓库分析、双仓库对比、十个维度评分、RAG 问答、Agent 日志和 Markdown / JSON 导出。设计上没有直接把完整仓库交给 LLM，而是先由规则工具提取事实，再让 LLM Agent 在受控上下文中进行语义解释和报告生成。

通过这次实现可以看到，智能分析工具的关键不只是“接入模型”，还包括如何选择输入、如何保留证据、如何处理失败、如何把结果呈现给用户。项目当前已经具备基础可用性，后续如果继续补充专业扫描工具和更细的语言分析能力，可以进一步提升分析结果的可靠性。

总体完成度较稳定。

后续可以继续接入真实漏洞库和安全工具，例如 OSV、pip-audit、npm audit、Bandit、Semgrep；增加 coverage 统计和 lint 结果；扩展 JavaScript、TypeScript、Java、Go 等语言的语法分析；为 LLM 输出加入更严格的 JSON Schema 校验；优化文件树和历史报告管理；将当前轻量 RAG 替换为向量检索，提高复杂问题的回答质量。
