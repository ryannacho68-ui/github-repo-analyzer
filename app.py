from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.agent_orchestrator import run_agent_workflow
from src.architecture_analyzer import analyze_architecture
from src.code_quality_analyzer import analyze_code_quality
from src.doc_checker import check_documentation
from src.file_tree import analyze_file_tree
from src.github_api_client import fetch_github_api_snapshot
from src.llm_reporter import DEFAULT_MODEL, generate_report, list_available_models
from src.project_overview_analyzer import analyze_project_overview
from src.rag_qa import answer_repository_question
from src.repo_loader import RepoLoadError, clone_or_use_cache
from src.report_exporter import save_markdown_report
from src.security_checker import check_security
from src.tech_stack_detector import detect_tech_stack


PROJECT_ROOT = Path(__file__).resolve().parent
ANALYZED_REPOS_DIR = PROJECT_ROOT / "data" / "analyzed_repos"
REPORTS_DIR = PROJECT_ROOT / "reports"


st.set_page_config(
    page_title="GitHub Repo Analyzer",
    page_icon="GH",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    _ensure_project_dirs()
    _inject_css()

    st.markdown(
        """
        <div class="topbar">
          <div>
            <div class="eyebrow">Static Analysis + Local LLM</div>
            <h1>GitHub 仓库智能分析器</h1>
          </div>
          <div class="status-pill">Dashboard</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    available_models = list_available_models()

    with st.container():
        with st.form("analysis_form", clear_on_submit=False, enter_to_submit=True, border=False):
            input_col, refresh_col, llm_col, model_col, button_col = st.columns([4.8, 1.1, 1.2, 1.7, 1.2])
            with input_col:
                repo_url_draft = st.text_input(
                    "GitHub URL",
                    placeholder="https://github.com/streamlit/streamlit-hello",
                    label_visibility="collapsed",
                    key="repo_url_draft",
                )
            with refresh_col:
                refresh = st.toggle("重新克隆", value=False)
            with llm_col:
                use_llm = st.toggle("Ollama", value=True)
            with model_col:
                model = _model_selector(available_models)
            with button_col:
                analyze_clicked = st.form_submit_button(
                    "开始分析",
                    type="primary",
                    use_container_width=True,
                )

    if analyze_clicked:
        submitted_repo_url = repo_url_draft.strip()
        if not submitted_repo_url:
            st.warning("请输入 GitHub 仓库 URL。")
        else:
            try:
                st.session_state["selected_model"] = model
                st.session_state["selected_use_llm"] = use_llm
                with st.spinner("正在分析中..."):
                    st.session_state["analysis_result"] = run_pipeline(submitted_repo_url, refresh, use_llm, model)
            except RepoLoadError as exc:
                st.error(str(exc))
            except Exception as exc:  # Defensive boundary for demo friendliness.
                st.error(f"分析过程中出现异常：{exc}")

    result = st.session_state.get("analysis_result")
    if result:
        render_dashboard(result)
    else:
        render_empty_state()


def run_pipeline(repo_url: str, refresh: bool, use_llm: bool, model: str) -> dict:
    progress = st.progress(0)
    status = st.empty()

    steps = [
        ("通过 GitHub API 获取仓库信息和 README", 8),
        ("克隆仓库或读取本地缓存", 18),
        ("分析项目结构和代码规模", 30),
        ("识别技术栈和依赖版本", 42),
        ("分析项目用途、README 内容和架构模式", 52),
        ("评估代码质量", 64),
        ("检查文档完整性", 74),
        ("扫描安全与工程规范", 84),
        ("运行 Multi-Agent 协作汇总", 92),
        ("LLM 正在分析中，生成结构化报告", 100),
    ]

    status.info(steps[0][0])
    github_api = fetch_github_api_snapshot(repo_url)
    progress.progress(steps[0][1])

    status.info(steps[1][0])
    repo_info = clone_or_use_cache(repo_url, ANALYZED_REPOS_DIR, refresh=refresh).to_dict()
    repo_path = Path(repo_info["local_path"])
    progress.progress(steps[1][1])

    status.info(steps[2][0])
    file_tree = analyze_file_tree(repo_path)
    progress.progress(steps[2][1])

    status.info(steps[3][0])
    tech_stack = detect_tech_stack(repo_path, file_tree)
    progress.progress(steps[3][1])

    status.info(steps[4][0])
    architecture = analyze_architecture(repo_path, file_tree, tech_stack)
    project_overview = analyze_project_overview(repo_path, github_api, tech_stack, file_tree, architecture)
    progress.progress(steps[4][1])

    status.info(steps[5][0])
    code_quality = analyze_code_quality(repo_path)
    progress.progress(steps[5][1])

    status.info(steps[6][0])
    documentation = check_documentation(repo_path)
    progress.progress(steps[6][1])

    status.info(steps[7][0])
    security = check_security(repo_path)
    progress.progress(steps[7][1])

    analysis = {
        "repo_info": repo_info,
        "github_api": github_api,
        "file_tree": file_tree,
        "tech_stack": tech_stack,
        "project_overview": project_overview,
        "architecture": architecture,
        "code_quality": code_quality,
        "documentation": documentation,
        "security": security,
        "analysis_options": {"use_llm": use_llm, "model": model},
    }

    status.info(steps[8][0])
    analysis["agents"] = run_agent_workflow(analysis)
    progress.progress(steps[8][1])

    status.info(steps[9][0])
    report_result = generate_report(analysis, model=model, use_llm=use_llm)
    analysis["report"] = report_result["report"]
    analysis["report_meta"] = {
        "mode": report_result["mode"],
        "model": report_result["model"],
        "message": report_result["message"],
    }
    progress.progress(steps[9][1])
    status.success("分析完成")
    return analysis


def render_dashboard(result: dict) -> None:
    repo = result["repo_info"]
    file_tree = result["file_tree"]
    tech_stack = result["tech_stack"]
    quality = result["code_quality"]
    docs = result["documentation"]
    security = result["security"]
    github_api = result.get("github_api") or {}
    architecture = result.get("architecture") or {}
    overview = result.get("project_overview") or {}

    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
    render_overview_band(result)

    kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)
    kpi1.metric("文件总数", file_tree["total_files"])
    kpi2.metric("代码行数", file_tree.get("total_code_lines", 0))
    kpi3.metric("主要语言", tech_stack["main_language"])
    kpi4.metric("项目类型", overview.get("project_type", "Unknown"))
    kpi5.metric("代码质量", f'{quality["score"]}/100')
    kpi6.metric("风险项", len(security["risks"]))

    left, center, right = st.columns([1.25, 1.45, 1.2], gap="large")

    with left:
        st.markdown("### 仓库信息")
        st.markdown(
            f"""
            <div class="glass-card">
              <div class="card-title">{repo['owner']} / {repo['name']}</div>
              <div class="muted">{repo['web_url']}</div>
              <div class="mini-grid">
                <span>来源</span><strong>{'缓存' if repo['from_cache'] else '新克隆'}</strong>
                <span>大小</span><strong>{file_tree['total_size_kb']} KB</strong>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if github_api.get("available"):
            api_repo = github_api.get("repo") or {}
            st.markdown(
                f"""
                <div class="glass-card">
                  <div class="card-title">GitHub API 快照</div>
                  <div class="mini-grid">
                    <span>Stars</span><strong>{api_repo.get('stars', 0)}</strong>
                    <span>Forks</span><strong>{api_repo.get('forks', 0)}</strong>
                    <span>Issues</span><strong>{api_repo.get('open_issues', 0)}</strong>
                    <span>默认分支</span><strong>{api_repo.get('default_branch', 'Unknown')}</strong>
                    <span>License</span><strong>{api_repo.get('license', 'None')}</strong>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif github_api.get("error"):
            st.caption(f"GitHub API 未获取成功：{github_api.get('error')}")

        st.markdown("### 技术栈")
        _badge_block(tech_stack.get("frameworks") or ["未识别到框架"])
        with st.expander("依赖与工程工具", expanded=True):
            st.write("工程工具：", ", ".join(tech_stack.get("tools") or ["未识别"]))
            for group, deps in (tech_stack.get("dependencies") or {}).items():
                st.caption(f"{group} dependencies")
                st.write(", ".join(deps[:40]) if deps else "无")
            for group, specs in (tech_stack.get("dependency_versions") or {}).items():
                with st.expander(f"{group} 版本明细", expanded=False):
                    st.write(", ".join(specs[:60]) if specs else "未识别到版本")

        st.markdown("### 文件统计")
        category_df = _category_dataframe(file_tree)
        if not category_df.empty:
            fig = px.pie(
                category_df,
                names="类别",
                values="数量",
                hole=0.55,
                color_discrete_sequence=["#5eead4", "#fbbf24", "#a78bfa", "#fb7185", "#94a3b8"],
            )
            fig.update_layout(
                height=270,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#dbeafe",
                margin=dict(l=0, r=0, t=10, b=10),
                showlegend=True,
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 评分")
        st.plotly_chart(_score_radar_figure(result), use_container_width=True)
        st.progress(quality["score"] / 100, text=f"代码质量 {quality['score']}/100")
        st.progress(docs["score"] / 100, text=f"文档完整性 {docs['score']}/100")
        st.progress(security["score"] / 100, text=f"安全规范 {security['score']}/100")

    with center:
        st.markdown("### 架构分析")
        with st.container(border=True):
            arch_cols = st.columns([1.2, 0.8])
            arch_cols[0].metric("结构模式", architecture.get("pattern", "Unknown"))
            arch_cols[1].metric("置信度", f"{round((architecture.get('confidence', 0) or 0) * 100)}%")
            _badge_block(architecture.get("style_tags") or ["轻量仓库"])
            if architecture.get("entry_points"):
                st.write("入口文件：", ", ".join(architecture.get("entry_points")))
            if architecture.get("modules"):
                st.dataframe(pd.DataFrame(architecture.get("modules")), use_container_width=True, hide_index=True)
            for item in architecture.get("rationale") or []:
                st.caption(item)

        st.markdown("### 文件树结构")
        with st.container(border=True):
            st.code(file_tree.get("tree", ""), language="text")

        st.markdown("### 目录分析")
        dir_df = pd.DataFrame(file_tree.get("directory_summary") or [])
        if not dir_df.empty:
            st.dataframe(dir_df, use_container_width=True, hide_index=True)
        else:
            st.info("未生成目录统计。")

        st.markdown("### 最大文件 Top 10")
        largest_df = pd.DataFrame(file_tree.get("largest_files") or [])
        if not largest_df.empty:
            st.dataframe(largest_df[["path", "size_kb", "category"]], use_container_width=True, hide_index=True)

        st.markdown("### 风险检测")
        risks = security.get("risks") or []
        if risks:
            st.dataframe(
                pd.DataFrame(risks)[["severity", "category", "path", "message"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success("未发现明显安全与工程规范风险。")

    with right:
        render_qa_panel(result)

        st.markdown("### 改进建议")
        with st.expander("代码质量扣分原因", expanded=True):
            for item in quality.get("deductions") or []:
                st.write(f"- {item}")
        with st.expander("文档改进建议", expanded=True):
            for item in docs.get("suggestions") or []:
                st.write(f"- {item}")
        with st.expander("工程规范问题", expanded=True):
            if risks:
                for risk in risks[:12]:
                    st.write(f"- [{risk['severity']}] {risk['path']}：{risk['message']}")
            else:
                st.write("- 暂未发现明显问题。")

        st.markdown("### 报告导出")
        repo_name = f"{repo['owner']}_{repo['name']}"
        export_col, download_col = st.columns(2)
        with export_col:
            if st.button("保存报告", use_container_width=True):
                report_path = save_markdown_report(repo_name, result["report"], REPORTS_DIR)
                st.success(f"已保存到 {report_path.relative_to(PROJECT_ROOT)}")
        with download_col:
            st.download_button(
                "下载 Markdown",
                data=result["report"].encode("utf-8"),
                file_name=f"{repo_name}_analysis.md",
                mime="text/markdown",
                use_container_width=True,
            )

    render_report_workspace(result)


def render_overview_band(result: dict) -> None:
    overview = result.get("project_overview") or {}
    github_api = result.get("github_api") or {}
    api_repo = github_api.get("repo") or {}
    evidence = overview.get("evidence") or []

    st.markdown("### 项目内容概览")
    overview_col, meta_col, evidence_col = st.columns([1.55, 1.0, 1.1], gap="large")
    with overview_col:
        st.markdown(
            f"""
            <div class="glass-card overview-card">
              <div class="card-title">{overview.get('project_type', '通用代码仓库')}</div>
              <div class="overview-purpose">{overview.get('purpose', '暂未识别到明确项目用途。')}</div>
              <div class="muted">目标用户：{overview.get('target_users', '开发者')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if overview.get("keywords"):
            _badge_block(overview.get("keywords"))

    with meta_col:
        st.markdown(
            f"""
            <div class="glass-card">
              <div class="card-title">判断信号</div>
              <div class="mini-grid">
                <span>置信度</span><strong>{overview.get('confidence', 0)}/100</strong>
                <span>默认分支</span><strong>{api_repo.get('default_branch', 'Unknown')}</strong>
                <span>Stars</span><strong>{api_repo.get('stars', 0)}</strong>
                <span>License</span><strong>{api_repo.get('license', 'None')}</strong>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with evidence_col:
        with st.container(border=True):
            st.markdown("**内容判断依据**")
            if evidence:
                for item in evidence[:3]:
                    st.caption(f"{item.get('source')}: {item.get('text')}")
            else:
                st.caption("暂无 README 或 GitHub 描述证据。")
            with st.expander("查看更多依据", expanded=False):
                if evidence:
                    st.dataframe(pd.DataFrame(evidence), use_container_width=True, hide_index=True)
                for item in overview.get("limitations") or []:
                    st.caption(item)


def render_report_workspace(result: dict) -> None:
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
    report_tab, agent_tab, detail_tab = st.tabs(["AI 总结报告", "Multi-Agent 日志", "详细分析数据"])

    with report_tab:
        st.caption(result["report_meta"]["message"])
        with st.container(border=True):
            st.markdown(result["report"])

    with agent_tab:
        render_agent_logs(result)

    with detail_tab:
        col1, col2 = st.columns(2, gap="large")
        with col1:
            st.markdown("#### 技术栈")
            st.json(result.get("tech_stack") or {})
        with col2:
            st.markdown("#### 项目概览")
            st.json(result.get("project_overview") or {})
        st.markdown("#### 安全扫描")
        st.json(result.get("security") or {})


def render_qa_panel(result: dict) -> None:
    st.markdown("### 仓库代码问答")
    repo = result["repo_info"]
    options = result.get("analysis_options") or {}
    question_key = f"qa_question_{repo['safe_name']}"
    answer_key = f"qa_answer_{repo['safe_name']}"

    with st.form(f"qa_form_{repo['safe_name']}", clear_on_submit=False, enter_to_submit=True, border=False):
        question = st.text_input(
            "向仓库提问",
            placeholder="例如：这个项目怎么在本地跑起来？数据库模型有哪些？",
            label_visibility="collapsed",
            key=question_key,
        )
        ask_clicked = st.form_submit_button(
            "RAG 提问",
            use_container_width=True,
        )

    if ask_clicked:
        submitted_question = question.strip()
        if not submitted_question:
            st.warning("请输入要提问的内容。")
        else:
            with st.spinner("正在检索仓库片段并生成回答..."):
                qa_result = answer_repository_question(
                    submitted_question,
                    Path(repo["local_path"]),
                    result,
                    model=options.get("model") or st.session_state.get("selected_model") or DEFAULT_MODEL,
                    use_llm=bool(options.get("use_llm", st.session_state.get("selected_use_llm", True))),
                )
                st.session_state[answer_key] = qa_result

    qa_result = st.session_state.get(answer_key)
    if qa_result:
        st.caption(qa_result.get("message", ""))
        st.markdown(qa_result.get("answer", ""))
        sources = qa_result.get("sources") or []
        if sources:
            with st.expander("检索来源", expanded=False):
                st.dataframe(pd.DataFrame(sources), use_container_width=True, hide_index=True)


def render_agent_logs(result: dict) -> None:
    agents = result.get("agents") or {}
    logs = agents.get("logs") or []
    st.markdown("### Multi-Agent 协作日志")
    if not logs:
        st.info("暂无 Agent 日志。")
        return

    summary_df = pd.DataFrame(
        [
            {
                "agent": item["agent"],
                "input": item["input"],
                "elapsed_ms": item["elapsed_ms"],
                "tokens": item["token_estimate"],
                "status": item["status"],
            }
            for item in logs
        ]
    )
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    with st.expander("查看各 Agent 结构化输出", expanded=False):
        for item in logs:
            st.caption(item["agent"])
            st.json(item["output"])
    st.caption(
        f"总耗时 {agents.get('total_elapsed_ms', 0)} ms，"
        f"估算 token {agents.get('total_token_estimate', 0)}。"
    )


def render_empty_state() -> None:
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    col1.metric("静态分析", "待运行")
    col2.metric("LLM 报告", "待生成")
    col3.metric("导出报告", "Markdown")
    st.markdown(
        """
        <div class="empty-panel">
          <div class="empty-title">输入公开 GitHub 仓库 URL 后开始分析</div>
          <div class="muted">系统会先克隆仓库并执行结构、技术栈、质量、文档和安全扫描，再基于结构化结果生成报告。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _model_selector(available_models: list[str]) -> str:
    if not available_models:
        return st.text_input("模型", value=DEFAULT_MODEL, label_visibility="collapsed")

    preferred = DEFAULT_MODEL if DEFAULT_MODEL in available_models else available_models[0]
    for candidate in available_models:
        if candidate.startswith("qwen2.5"):
            preferred = candidate
            break
    return st.selectbox(
        "模型",
        options=available_models,
        index=available_models.index(preferred),
        label_visibility="collapsed",
    )


def _category_dataframe(file_tree: dict) -> pd.DataFrame:
    rows = [
        {"类别": category, "数量": count}
        for category, count in (file_tree.get("category_counts") or {}).items()
    ]
    return pd.DataFrame(rows)


def _score_radar_figure(result: dict) -> go.Figure:
    quality = result.get("code_quality") or {}
    docs = result.get("documentation") or {}
    security = result.get("security") or {}
    tech_stack = result.get("tech_stack") or {}
    architecture = result.get("architecture") or {}
    tests = quality.get("tests") or {}
    tools = set(tech_stack.get("tools") or [])

    dimensions = ["代码质量", "文档", "安全规范", "测试", "部署", "架构清晰度"]
    values = [
        quality.get("score", 0),
        docs.get("score", 0),
        security.get("score", 0),
        100 if tests.get("has_tests") else 35,
        100 if {"Docker", "Docker Compose", "GitHub Actions"} & tools else 45,
        round((architecture.get("confidence", 0) or 0) * 100),
    ]
    closed_dimensions = dimensions + [dimensions[0]]
    closed_values = values + [values[0]]

    fig = go.Figure(
        data=[
            go.Scatterpolar(
                r=closed_values,
                theta=closed_dimensions,
                fill="toself",
                line_color="#5eead4",
                fillcolor="rgba(94, 234, 212, 0.22)",
                name="Score",
            )
        ]
    )
    fig.update_layout(
        height=280,
        margin=dict(l=18, r=18, t=22, b=18),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#dbeafe",
        showlegend=False,
        polar=dict(
            bgcolor="rgba(15, 23, 42, 0.35)",
            radialaxis=dict(visible=True, range=[0, 100], color="#94a3b8"),
            angularaxis=dict(color="#bfdbfe"),
        ),
    )
    return fig


def _badge_block(items: list[str]) -> None:
    badges = "".join(f'<span class="badge">{item}</span>' for item in items[:16])
    st.markdown(f'<div class="badge-wrap">{badges}</div>', unsafe_allow_html=True)


def _ensure_project_dirs() -> None:
    ANALYZED_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(20, 184, 166, 0.16), transparent 32rem),
                linear-gradient(135deg, #070b14 0%, #101827 46%, #111827 100%);
            color: #e5e7eb;
        }
        [data-testid="stHeader"] { background: rgba(7, 11, 20, 0.6); }
        .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1680px; }
        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1.1rem 1.2rem;
            border: 1px solid rgba(148, 163, 184, 0.24);
            border-radius: 8px;
            background: rgba(15, 23, 42, 0.76);
            box-shadow: 0 22px 60px rgba(0, 0, 0, 0.24);
            margin-bottom: 1rem;
        }
        .topbar h1 {
            font-size: 2rem;
            line-height: 1.1;
            margin: 0.2rem 0 0;
            letter-spacing: 0;
            color: #f8fafc;
        }
        .eyebrow {
            color: #67e8f9;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0;
            font-weight: 700;
        }
        .status-pill, .badge {
            display: inline-flex;
            align-items: center;
            border: 1px solid rgba(94, 234, 212, 0.35);
            background: rgba(20, 184, 166, 0.12);
            color: #ccfbf1;
            border-radius: 8px;
            padding: 0.34rem 0.58rem;
            font-size: 0.78rem;
            font-weight: 700;
        }
        .badge-wrap { display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0.2rem 0 0.85rem; }
        .glass-card, .empty-panel {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.72);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
        }
        .empty-panel { min-height: 190px; display: flex; flex-direction: column; justify-content: center; }
        .empty-title, .card-title {
            color: #f8fafc;
            font-size: 1.05rem;
            font-weight: 800;
            margin-bottom: 0.35rem;
            word-break: break-word;
        }
        .overview-card {
            min-height: 138px;
        }
        .overview-purpose {
            color: #dbeafe;
            font-size: 1rem;
            line-height: 1.55;
            margin: 0.5rem 0 0.85rem;
            word-break: break-word;
        }
        .muted { color: #94a3b8; font-size: 0.88rem; word-break: break-word; }
        .mini-grid {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 0.55rem;
            margin-top: 1rem;
            color: #94a3b8;
            font-size: 0.88rem;
        }
        .mini-grid strong { color: #f8fafc; }
        .section-gap { height: 0.7rem; }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.7);
            border-radius: 8px;
            padding: 0.75rem 0.85rem;
        }
        div[data-testid="stMetricValue"] { color: #f8fafc; }
        div[data-testid="stMetricLabel"] { color: #bfdbfe; }
        div[data-testid="stExpander"], div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: rgba(148, 163, 184, 0.22) !important;
            background: rgba(15, 23, 42, 0.48);
            border-radius: 8px;
        }
        .stDataFrame, .stCodeBlock { border-radius: 8px; overflow: hidden; }
        h3 { color: #e0f2fe; letter-spacing: 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
