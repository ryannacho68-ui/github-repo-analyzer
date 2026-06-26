# GitHub 仓库智能分析器 Vibe Coding Prompt 记录

本记录按照项目实际开发过程进行阶段化整理，保留每个阶段的关键 Prompt、AI 回复要点、人工判断和修正动作。开发过程中并不是一次性生成完整系统，而是围绕产品需求，从最小可运行版本开始，逐步补充静态分析、多 Agent、Ollama、RAG、双仓库对比、页面交互、测试和项目文档。

## 一、需求理解与项目拆解

### Prompt 1：明确项目需求

**我的提问：**

我需要完成“GitHub 仓库智能分析器”。要求用户输入 GitHub 仓库 URL 后，系统自动获取代码，先做确定性静态分析，再把结构化结果交给 LLM 生成报告。项目要用 Streamlit，支持 Ollama，本地可运行，还要有 README、设计文档和运行说明。请帮我拆解项目结构和实现路线。

**AI 回复要点：**

AI 将系统拆成仓库获取、文件树分析、技术栈识别、代码质量分析、文档检查、安全检查、LLM 报告生成、Streamlit Dashboard、报告导出等模块，并建议使用 `src/` 目录组织业务逻辑，`app.py` 负责页面入口。

**我的修正与决定：**

我确认项目不能做成“把网址丢给 LLM 总结”的形式，因此保留“静态分析先行”的路线。初版目标定为：先能克隆一个公开仓库，输出文件统计、技术栈、质量评分和基础报告，再继续增强页面和 Agent。

## 二、项目骨架与基础模块

### Prompt 2：生成第一阶段代码

**我的提问：**

我现在开始手动搭建，先给我第一阶段代码，并解释代码。第一阶段只要求项目能运行，能输入 GitHub URL，克隆仓库并做基础文件统计。

**AI 回复要点：**

AI 给出了基础目录结构、`requirements.txt`、`.gitignore`、`app.py`、`repo_loader.py`、`file_tree.py` 等文件的初版实现，并解释了每个函数的作用。例如 `clone_repository` 负责下载仓库，`build_file_tree` 负责遍历目录并过滤 `.git`、`venv`、`node_modules` 等目录。

**我的修正与决定：**

我手动建立项目目录，先保证 `pip install -r requirements.txt` 和 `streamlit run app.py` 能启动。这个阶段没有急着接 LLM，而是先验证仓库获取和文件统计，避免后续页面做出来但没有真实数据支撑。

## 三、静态分析工具增强

### Prompt 3：补充技术栈、代码质量和文档检查

**我的提问：**

请继续实现技术栈识别、代码质量分析、文档完整性检查和安全风险检查。要求使用 Python 程序分析，不要直接让 LLM 猜。

**AI 回复要点：**

AI 增加了多个静态分析模块：`tech_stack_detector.py` 通过 `requirements.txt`、`package.json`、`pyproject.toml`、`Dockerfile` 等文件识别语言、框架和工程工具；`code_quality_analyzer.py` 使用 AST 统计函数、类、长函数、长文件和 TODO；`doc_checker.py` 检查 README、LICENSE、安装方式和运行方式；`security_checker.py` 检查 `.env`、敏感关键词、大文件和不应提交的目录。

**我的修正与决定：**

我保留了确定性规则作为评分依据，并要求每个模块输出结构化数据，而不是直接输出一段自然语言。这是后续多 Agent 和报告生成的基础。

## 四、Ollama 与降级报告

### Prompt 4：接入本地大模型

**我的提问：**

项目要求使用 Ollama，默认模型是 `qwen2.5:7b`。如果 Ollama 不可用，也要能输出基础分析报告。请实现 LLM 报告模块。

**AI 回复要点：**

AI 实现了 `llm_reporter.py` 或后续的 `llm_client.py`，通过本地接口 `http://localhost:11434/api/generate` 调用 Ollama。输入内容只包含前面静态分析得到的结构化结果，不包含整个仓库源码。如果 Ollama 请求失败，系统会自动退化为模板报告，并在页面显示降级原因。

**我的修正与决定：**

我运行时遇到过 `404 Client Error: Not Found for url: http://localhost:11434/api/generate`，因此确认必须保留无 LLM 模式。后续我也把页面中的提示改得更友好，让用户能区分“静态分析成功”和“LLM 未启用”。

## 五、多 Agent 架构重构

### Prompt 5：明确 Agent 和工具的分工

**我的提问：**

现在这些 Agent 的作用是什么？是自己分析，还是等那些 Python 文件生成好后仅仅总结？项目要求里写了多 Agent 分析架构，我希望项目按以下结构优化：Architecture Agent 调用 file_tree.py 和 architecture_analyzer.py，Tech Stack Agent 调用 tech_stack_detector.py，Code Quality Agent 调用 code_quality_analyzer.py，Document Agent 调用 doc_checker.py 和 GitHub README API，Summary Agent 汇总所有 Agent 输出。

**AI 回复要点：**

AI 解释了“工具”和“Agent”的边界：工具负责提取事实，Agent 负责组织输入、调用工具、根据证据判断并输出结构化结果。随后项目增加或重构了 `src/agents/` 目录，包括 `overview_agent.py`、`tech_stack_agent.py`、`architecture_agent.py`、`code_quality_agent.py`、`documentation_agent.py`、`test_deploy_agent.py`、`risk_agent.py`、`summary_agent.py` 和 `comparison_agent.py`。

**我的修正与决定：**

我没有把所有分析都交给 LLM，而是采用“规则工具 + LLM Agent”的混合方式。Overview Agent 和 Tech Stack Agent 可以调用 Ollama 做语义补充；Code Quality、Risk、Test Deploy 主要使用规则；Summary Agent 汇总所有 Agent 的结构化输出。这样既符合 Multi-Agent 架构设计，也能减少 LLM 幻觉。

## 六、GitHub API 与仓库上下文

### Prompt 6：补充 GitHub API 获取信息

**我的提问：**

题目要求通过 GitHub API 获取仓库信息、文件结构和 README。请检查当前项目是否符合，如果不符合就补充。

**AI 回复要点：**

AI 增强了仓库上下文构建流程，增加 GitHub API 的仓库元信息、README 获取、文件列表辅助信息，并在 API 失败时回退到本地 git clone 的分析结果。项目使用 `RepositoryContext` 保存仓库名、URL、本地路径、README、依赖文件、文件树和统计结果。

**我的修正与决定：**

我测试自己的 GitHub 仓库时遇到过 API 频率限制 `403 rate limit exceeded`。因此我要求项目不能强依赖 GitHub API，API 获取失败时仍然可以通过本地仓库文件完成主要分析。

## 七、RAG 仓库问答

### Prompt 7：增加对仓库代码提问功能

**我的提问：**

使用场景里有“对仓库代码提问”，例如问数据库模型有哪些、怎么本地运行起来。请给项目增加 RAG 问答功能，但不要把整个仓库直接塞给 LLM。

**AI 回复要点：**

AI 增加了代码片段抽取、简单检索和回答生成逻辑。系统优先从 README、依赖文件、入口文件、配置文件和核心代码中抽取片段，再根据用户问题匹配相关内容。如果 Ollama 可用，就基于检索到的片段回答；如果不可用，就返回基于规则的提示和可能的文件位置。

**我的修正与决定：**

我发现有些回答会显示“暂未识别到明确启动命令”，于是要求增强 README 和代码特征分析，例如识别 `streamlit run app.py`、`flask run`、`uvicorn`、`python manage.py runserver` 等启动线索。这样问答模块虽然不是完整向量数据库版本，但已经体现了 RAG 的基本思想：先检索证据，再生成回答。

## 八、Streamlit Dashboard 交互与排版

### Prompt 8：从原型输出改成产品化页面

**我的提问：**

最终项目必须是有产品感的 Web Dashboard，而不是命令行输出搬到网页。请优化页面，做成类似 GitHub Insights 或 AI Code Review 工具的深色 Dashboard。左侧显示仓库信息、技术栈和评分，中间显示文件树、目录分析和风险检测，右侧显示 AI 总结和改进建议。

**AI 回复要点：**

AI 使用 Streamlit 的 `columns`、`container`、`metric`、`expander` 和 Plotly 图表重构页面。页面增加了进度条、状态提示、技术栈标签、评分卡片、文件类型比例图、雷达图、Agent 日志和报告下载按钮。

**我的修正与决定：**

我在实际运行时发现右侧太满、左侧太空，文件树全部堆在一行，风险检测区域既能横向又能纵向滚动，体验不好。于是继续要求优化三栏宽度、滚动区域、文件树排版、按钮禁用状态和分析完成后的恢复状态。

## 九、按钮状态与输入体验

### Prompt 9：优化分析按钮和 RAG 按钮

**我的提问：**

当输入链接开始分析时，按钮要变成灰色无法交互，完成后再恢复。RAG 提问按钮也要有状态显示。另外链接输入和 RAG 输入的提交方式需要调整。

**AI 回复要点：**

AI 调整了 Streamlit 的状态管理，通过 `st.session_state` 保存分析中状态、当前结果和按钮状态。分析开始后禁用按钮并显示“正在分析中”，完成或异常后恢复按钮。RAG 提问也增加了加载提示，避免用户重复点击。

**我的修正与决定：**

我一开始要求不能用回车提交，后来发现使用时回车更自然，又改成希望链接输入可以通过回车直接触发分析。于是项目最终保留了按钮提交，同时兼顾回车触发分析的体验。

## 十、双仓库对比功能

### Prompt 10：增加可选对比功能

**我的提问：**

请新增“输入两个 GitHub 仓库 URL 进行对比”的功能，包括评分对比、技术栈差异、架构差异和适用场景建议。

**AI 回复要点：**

AI 增加了 `comparison_agent.py` 和对比页面。系统分别对两个仓库执行同一套分析流程，再将两个结果输入 Comparison Agent，生成表格、雷达图和自然语言对比结论。

**我的修正与决定：**

测试时双仓库对比出现过 `AttributeError: 'str' object has no attribute 'get'`，原因是雷达图函数假设输入一定是字典列表，但实际某些结果是字符串。修复后对比模块增加了输入格式兼容处理，避免页面因为单个字段异常崩溃。

## 十一、Agent 日志和可解释性

### Prompt 11：检查所有 Agent 是否正常工作

**我的提问：**

阅读日志文件，看看所有 Agent 是否正常工作，LLM 是否都正常调用，项目是否正常运作。Architecture Agent 是否调用 Ollama？如果不符合项目要求就优化。

**AI 回复要点：**

AI 检查了 `outputs/agent_logs/` 中的 Agent 日志字段，包括 `agent_name`、`tools_used`、`llm_used`、`model`、`score`、`status`、`output_summary` 和证据数量。对于 Architecture Agent，AI 解释了原先主要是规则分析，后来按要求加入 Ollama 语义分析，使其能够在规则识别结构模式后，再由 LLM 根据 README、目录角色和入口文件生成更自然的架构说明。

**我的修正与决定：**

我要求日志必须能用于技术说明：每个 Agent 输入什么、用了什么工具、是否用了 LLM、输出了什么结果。这样在解释“Agent 是不是只是名字”时，可以通过日志证明每个 Agent 有明确职责和输出。

## 十二、测试配置与缓存目录问题

### Prompt 12：修复 pytest 错误收集第三方仓库测试

**我的提问：**

运行 pytest 时会错误收集 `data/analyzed_repos/pallets_flask` 这个被分析的第三方仓库中的 tests，导致 `ModuleNotFoundError`。这不是项目本身测试失败，请修复测试配置，不要删除缓存目录。

**AI 回复要点：**

AI 新增或修改了 `pytest.ini`，设置 `testpaths = tests`、`python_files = test_*.py`，并在 `norecursedirs` 中排除 `.git`、`.venv`、`venv`、`__pycache__`、`data`、`outputs` 和 `data/analyzed_repos` 等目录。

**我的修正与决定：**

我保留 `data/analyzed_repos` 作为仓库缓存目录，只让 pytest 忽略它。这样测试只检查本项目的测试文件，不会被克隆下来的第三方项目干扰。

## 十三、编码格式与文件质量检查

### Prompt 13：检查 Raw 文件格式疑似损坏

**我的提问：**

我看到 GitHub Raw 里 `llm_client.py`、`analysis_models.py`、`requirements.txt` 好像被挤成一整行，`app.py` 里还有乱码。请检查是否真的有这个问题，并修复。

**AI 回复要点：**

AI 检查了本地文件内容，确认是否存在 `from __future__ import annotations import json` 这类非法语法，并运行 `python -m py_compile` 验证核心文件语法。对于 `requirements.txt`，检查是否一行一个依赖。对于页面乱码，修正中文按钮和状态提示。

**我的修正与决定：**

我把语法可运行性作为提交前的底线：先保证 `py_compile` 和 `pytest tests` 通过，再考虑页面美观和报告材料。

## 十四、效果较好的 Prompt 类型总结

开发过程中效果较好的 Prompt 主要有以下几类：

1. **带约束的实现 Prompt**
   例如“不要直接调用 LLM 总结仓库，必须先用 Python 做结构化分析”。这类约束能让 AI 生成的方案更符合项目目标。

2. **按模块拆分的 Prompt**
   例如“先实现仓库获取模块，再实现文件树分析模块”。分阶段提问比一次性要求完整项目更容易检查和修正。

3. **带错误信息的调试 Prompt**
   例如直接提供 `AttributeError: 'str' object has no attribute 'get'` 或 `403 rate limit exceeded`，AI 能更快定位问题。

4. **带页面体验要求的 Prompt**
   例如“右侧很满，左侧很空”“文件树不要堆在一起”“按钮分析中要禁用”。这类 Prompt 能让 Web 页面从原型输出逐步接近真实产品。

5. **要求解释设计取舍的 Prompt**
   例如“Agent 到底是不是调用 Ollama”“静态分析和 LLM 的分工是什么”。这些问题帮助我理解项目，而不是只复制代码。

## 十五、人工介入较多的地方

虽然 AI 能快速生成代码和文档，但整个项目中有不少地方需要人工判断：

- 根据项目目标决定不能把整个仓库直接交给 LLM；
- 判断哪些 Agent 应该调用 Ollama，哪些应该用规则工具；
- 根据本地运行结果修复 Ollama 不可用、GitHub API 限流、pytest 误收集等问题；
- 调整 Streamlit 页面布局，让 Dashboard 更适合真实使用；
- 检查 README、技术文档和报告，避免夸大项目能力；
- 用真实 GitHub 仓库测试分析流程，确认项目不是只在示例数据上可用。

通过这些迭代，项目最终形成了比较清晰的开发路径：先有可运行的静态分析工具，再有 Agent 封装，再接入 LLM，再做 Dashboard、RAG、对比和文档材料。
