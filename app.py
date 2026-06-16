from __future__ import annotations

from html import escape
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.github_api_client import fetch_github_api_snapshot
from src.llm_reporter import DEFAULT_MODEL, generate_report, list_available_models
from src.orchestrator import analyze_repository, compare_repositories
from src.rag_qa import answer_repository_question
from src.repo_loader import RepoLoadError, clone_or_use_cache
from src.report_generator import generate_comparison_markdown, generate_repository_markdown, save_agent_logs, save_report_files


PROJECT_ROOT = Path(__file__).resolve().parent
ANALYZED_REPOS_DIR = PROJECT_ROOT / "data" / "analyzed_repos"
REPORTS_DIR = PROJECT_ROOT / "reports"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


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

    single_tab, compare_tab, qa_tab = st.tabs(["单仓库分析", "双仓库对比", "仓库代码问答"])

    with single_tab:
        is_analyzing = bool(st.session_state.get("single_analysis_running"))
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
                refresh = st.toggle("重新克隆", value=False, key="single_refresh")
            with llm_col:
                use_llm = st.toggle("Ollama", value=True, key="single_llm")
            with model_col:
                model = _model_selector(available_models)
            with button_col:
                analyze_clicked = st.form_submit_button(
                    "正在分析中..." if is_analyzing else "开始分析",
                    type="primary",
                    use_container_width=True,
                    disabled=is_analyzing,
                )

        if analyze_clicked:
            submitted_repo_url = repo_url_draft.strip()
            if not submitted_repo_url:
                st.warning("请输入 GitHub 仓库 URL。")
            else:
                st.session_state.pop("single_analysis_error", None)
                st.session_state["single_pending_job"] = {
                    "repo_url": submitted_repo_url,
                    "refresh": refresh,
                    "use_llm": use_llm,
                    "model": model,
                }
                st.session_state["single_analysis_running"] = True
                st.rerun()

        if st.session_state.get("single_analysis_running"):
            job = st.session_state.get("single_pending_job") or {}
            try:
                st.session_state["selected_model"] = job.get("model") or model
                st.session_state["selected_use_llm"] = bool(job.get("use_llm", use_llm))
                with st.spinner("正在分析中..."):
                    st.session_state["analysis_result"] = run_pipeline(
                        job.get("repo_url", ""),
                        bool(job.get("refresh", False)),
                        bool(job.get("use_llm", True)),
                        job.get("model") or model,
                    )
                st.session_state.pop("single_analysis_error", None)
            except RepoLoadError as exc:
                st.session_state["single_analysis_error"] = str(exc)
            except Exception as exc:
                st.session_state["single_analysis_error"] = f"分析过程中出现异常：{exc}"
            finally:
                st.session_state["single_analysis_running"] = False
                st.session_state.pop("single_pending_job", None)
                st.rerun()

        if st.session_state.get("single_analysis_error"):
            st.error(st.session_state["single_analysis_error"])

        result = st.session_state.get("analysis_result")
        if result:
            render_dashboard(result)
        else:
            render_empty_state()

    with compare_tab:
        render_compare_workspace()

    with qa_tab:
        result = st.session_state.get("analysis_result")
        if result:
            render_qa_panel(result)
        else:
            st.info("请先在“单仓库分析”中完成一次分析，再进行仓库代码问答。")


def run_pipeline(repo_url: str, refresh: bool, use_llm: bool, model: str) -> dict:
    progress = st.progress(0)
    status = st.empty()
    def update(message: str, percent: int) -> None:
        status.info(message)
        progress.progress(percent)

    analysis = analyze_repository(repo_url, ANALYZED_REPOS_DIR, refresh=refresh, progress=update)
    analysis["analysis_options"] = {"use_llm": use_llm, "model": model}

    status.info("生成覆盖 10 个维度的结构化报告")
    structured_report = generate_repository_markdown(analysis)
    report_result = generate_report(analysis, model=model, use_llm=use_llm)
    if report_result["mode"] == "ollama":
        analysis["report"] = f"{report_result['report']}\n\n---\n\n{structured_report}"
    else:
        analysis["report"] = structured_report
    analysis["report_meta"] = {
        "mode": report_result["mode"],
        "model": report_result["model"],
        "message": f"已生成 10 维度结构化报告。{report_result['message']}",
    }
    repo = analysis.get("repo_info") or {}
    log_name = f"{repo.get('owner', 'repo')}_{repo.get('name', 'analysis')}"
    analysis["agent_log_path"] = save_agent_logs(log_name, analysis.get("agent_logs") or [], OUTPUTS_DIR)
    progress.progress(100)
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
    with kpi4:
        _scroll_metric("项目类型", overview.get("project_type", "Unknown"))
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
            st.info(f"GitHub API 暂不可用，已使用本地仓库继续分析：{github_api.get('error')}")

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
            with arch_cols[0]:
                _scroll_metric("结构模式", architecture.get("pattern", "Unknown"))
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
            _scroll_text_block(file_tree.get("tree", ""), height=360)

        st.markdown("### 目录分析")
        dir_df = pd.DataFrame(file_tree.get("directory_summary") or [])
        if not dir_df.empty:
            st.dataframe(dir_df, use_container_width=True, hide_index=True, height=240)
        else:
            st.info("未生成目录统计。")

        st.markdown("### 最大文件 Top 10")
        largest_df = pd.DataFrame(file_tree.get("largest_files") or [])
        if not largest_df.empty:
            st.dataframe(largest_df[["path", "size_kb", "category"]], use_container_width=True, hide_index=True, height=220)

        st.markdown("### 风险检测")
        risks = security.get("risks") or []
        if risks:
            _risk_list(risks)
        else:
            st.success("未发现明显安全与工程规范风险。")

    with right:
        render_dimension_score_panel(result)

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
        export_col, md_col, json_col = st.columns(3)
        with export_col:
            if st.button("保存报告", use_container_width=True):
                paths = save_report_files(repo_name, result["report"], result, OUTPUTS_DIR)
                st.success(f"已保存到 {Path(paths['markdown']).relative_to(PROJECT_ROOT)}")
        with md_col:
            st.download_button(
                "Markdown",
                data=result["report"].encode("utf-8"),
                file_name=f"{repo_name}_analysis.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with json_col:
            st.download_button(
                "JSON",
                data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"{repo_name}_analysis.json",
                mime="application/json",
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
              <div class="card-title scroll-title">{_html(overview.get('project_type', '通用代码仓库'))}</div>
              <div class="overview-purpose">{_html(overview.get('purpose', '暂未识别到明确项目用途。'))}</div>
              <div class="muted">目标用户：{_html(overview.get('target_users', '开发者'))}</div>
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


def render_dimension_score_panel(result: dict) -> None:
    st.markdown("### 10 维度评分")
    scores = result.get("dimension_scores") or {}
    if not scores:
        st.info("暂无维度评分。")
        return
    score_df = pd.DataFrame(
        [{"分析维度": key, "得分": value} for key, value in scores.items()]
    )
    st.dataframe(score_df, use_container_width=True, hide_index=True, height=285)
    summary = result.get("final_summary") or {}
    with st.expander("主要优点", expanded=False):
        for item in summary.get("strengths") or ["暂无明显优势。"]:
            st.write(f"- {item}")
    with st.expander("主要问题", expanded=False):
        for item in summary.get("issues") or ["暂无明显问题。"]:
            st.write(f"- {item}")


def render_compare_workspace() -> None:
    is_comparing = bool(st.session_state.get("comparison_running"))
    with st.form("compare_form", clear_on_submit=False, enter_to_submit=True, border=False):
        col_a, col_b, refresh_col, button_col = st.columns([3.2, 3.2, 1.1, 1.2])
        with col_a:
            repo_a = st.text_input(
                "仓库 A",
                placeholder="https://github.com/pallets/flask",
                label_visibility="collapsed",
                key="compare_repo_a",
            )
        with col_b:
            repo_b = st.text_input(
                "仓库 B",
                placeholder="https://github.com/fastapi/fastapi",
                label_visibility="collapsed",
                key="compare_repo_b",
            )
        with refresh_col:
            refresh = st.toggle("重新克隆", value=False, key="compare_refresh")
        with button_col:
            compare_clicked = st.form_submit_button(
                "正在对比中..." if is_comparing else "开始对比",
                type="primary",
                use_container_width=True,
                disabled=is_comparing,
            )

    if compare_clicked:
        if not repo_a.strip() or not repo_b.strip():
            st.warning("请输入两个 GitHub 仓库 URL。")
        else:
            st.session_state.pop("comparison_error", None)
            st.session_state["comparison_pending_job"] = {
                "repo_a": repo_a.strip(),
                "repo_b": repo_b.strip(),
                "refresh": refresh,
            }
            st.session_state["comparison_running"] = True
            st.rerun()

    if st.session_state.get("comparison_running"):
        job = st.session_state.get("comparison_pending_job") or {}
        try:
            with st.spinner("正在对比分析中..."):
                st.session_state["comparison_result"] = run_compare_pipeline(
                    job.get("repo_a", ""),
                    job.get("repo_b", ""),
                    bool(job.get("refresh", False)),
                )
            st.session_state.pop("comparison_error", None)
        except RepoLoadError as exc:
            st.session_state["comparison_error"] = str(exc)
        except Exception as exc:
            st.session_state["comparison_error"] = f"对比过程中出现异常：{exc}"
        finally:
            st.session_state["comparison_running"] = False
            st.session_state.pop("comparison_pending_job", None)
            st.rerun()

    if st.session_state.get("comparison_error"):
        st.error(st.session_state["comparison_error"])

    result = st.session_state.get("comparison_result")
    if result:
        render_comparison_dashboard(result)
    else:
        st.markdown(
            """
            <div class="empty-panel">
              <div class="empty-title">输入两个公开 GitHub 仓库 URL 后开始对比</div>
              <div class="muted">系统会分别运行单仓库 Multi-Agent 分析，再由 Comparison Agent 进行 10 个维度横向对比。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def run_compare_pipeline(repo_a: str, repo_b: str, refresh: bool) -> dict:
    progress = st.progress(0)
    status = st.empty()

    def update(message: str, percent: int) -> None:
        status.info(message)
        progress.progress(percent)

    result = compare_repositories(repo_a, repo_b, ANALYZED_REPOS_DIR, refresh=refresh, progress=update)
    report = generate_comparison_markdown(result)
    result["report"] = report
    result["report_meta"] = {
        "mode": "comparison-template",
        "message": "已生成双仓库 10 维度对比报告。",
    }
    comparison = result.get("comparison") or {}
    name = f"compare_{(comparison.get('repo_a') or {}).get('name', 'repo_a')}_{(comparison.get('repo_b') or {}).get('name', 'repo_b')}"
    result["agent_log_path"] = save_agent_logs(name, result.get("agent_logs") or [], OUTPUTS_DIR)
    progress.progress(100)
    status.success("对比完成")
    return result


def render_comparison_dashboard(result: dict) -> None:
    comparison = result.get("comparison") or {}
    repo_a = comparison.get("repo_a") or {}
    repo_b = comparison.get("repo_b") or {}

    st.markdown("### 总体结论")
    st.markdown(
        f"""
        <div class="glass-card">
          <div class="card-title">{repo_a.get('owner')}/{repo_a.get('name')} vs {repo_b.get('owner')}/{repo_b.get('name')}</div>
          <div class="overview-purpose">{comparison.get('overall_conclusion', '暂无结论。')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    k1, k2, k3 = st.columns(3)
    k1.metric("仓库 A 总分", repo_a.get("overall_score", 0))
    k2.metric("仓库 B 总分", repo_b.get("overall_score", 0))
    k3.metric("对比维度", len(comparison.get("dimension_comparison") or []))

    left, right = st.columns([1.35, 1.0], gap="large")
    with left:
        st.markdown("### 维度评分对比")
        rows = comparison.get("dimension_comparison") or []
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.plotly_chart(_comparison_radar_figure(rows), use_container_width=True)

    with right:
        st.markdown("### 适用场景建议")
        for key, value in (comparison.get("scenario_recommendations") or {}).items():
            st.write(f"- **{key}**：{value}")

        st.markdown("### 报告导出")
        name = f"compare_{repo_a.get('name', 'repo_a')}_{repo_b.get('name', 'repo_b')}"
        save_col, md_col, json_col = st.columns(3)
        with save_col:
            if st.button("保存对比", use_container_width=True):
                paths = save_report_files(name, result["report"], result, OUTPUTS_DIR)
                st.success(f"已保存到 {Path(paths['markdown']).relative_to(PROJECT_ROOT)}")
        with md_col:
            st.download_button(
                "Markdown",
                data=result["report"].encode("utf-8"),
                file_name=f"{name}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with json_col:
            st.download_button(
                "JSON",
                data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"{name}.json",
                mime="application/json",
                use_container_width=True,
            )

    detail_tabs = st.tabs(["技术栈差异", "架构差异", "质量差异", "文档测试部署", "风险差异", "对比报告"])
    with detail_tabs[0]:
        st.json(comparison.get("tech_stack_comparison") or {})
    with detail_tabs[1]:
        st.json(comparison.get("architecture_comparison") or {})
    with detail_tabs[2]:
        st.json(comparison.get("quality_comparison") or {})
    with detail_tabs[3]:
        st.json(comparison.get("documentation_test_deploy_comparison") or {})
    with detail_tabs[4]:
        st.json(comparison.get("risk_comparison") or {})
    with detail_tabs[5]:
        st.markdown(result.get("report", ""))


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
    scores = result.get("dimension_scores") or {}
    if scores:
        dimensions = list(scores.keys())
        values = [round(float(value) * 10, 1) for value in scores.values()]
    else:
        quality = result.get("code_quality") or {}
        docs = result.get("documentation") or {}
        security = result.get("security") or {}
        dimensions = ["代码质量", "文档", "安全规范"]
        values = [quality.get("score", 0), docs.get("score", 0), security.get("score", 0)]
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


def _comparison_radar_figure(rows: list[dict]) -> go.Figure:
    if not rows:
        return go.Figure()
    dimensions = [row.get("分析维度") for row in rows]
    values_a = [round(float(row.get("仓库 A 得分") or 0) * 10, 1) for row in rows]
    values_b = [round(float(row.get("仓库 B 得分") or 0) * 10, 1) for row in rows]
    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=values_a + [values_a[0]],
            theta=dimensions + [dimensions[0]],
            fill="toself",
            name="仓库 A",
            line_color="#5eead4",
            fillcolor="rgba(94, 234, 212, 0.18)",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=values_b + [values_b[0]],
            theta=dimensions + [dimensions[0]],
            fill="toself",
            name="仓库 B",
            line_color="#fbbf24",
            fillcolor="rgba(251, 191, 36, 0.14)",
        )
    )
    fig.update_layout(
        height=360,
        margin=dict(l=18, r=18, t=22, b=18),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#dbeafe",
        polar=dict(
            bgcolor="rgba(15, 23, 42, 0.35)",
            radialaxis=dict(visible=True, range=[0, 100], color="#94a3b8"),
            angularaxis=dict(color="#bfdbfe"),
        ),
    )
    return fig


def _badge_block(items: list[str]) -> None:
    badges = "".join(f'<span class="badge">{_html(item)}</span>' for item in items[:16])
    st.markdown(f'<div class="badge-wrap">{badges}</div>', unsafe_allow_html=True)


def _html(value: object) -> str:
    return escape(str(value or ""))


def _scroll_metric(label: str, value: object) -> None:
    html = (
        '<div class="scroll-metric">'
        f'<div class="metric-label">{_html(label)}</div>'
        f'<div class="metric-value-x">{_html(value)}</div>'
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _scroll_text_block(text: str, height: int = 320) -> None:
    st.markdown(
        f'<pre class="tree-scroll" style="max-height:{height}px;">{_html(text or "暂无文件树。")}</pre>',
        unsafe_allow_html=True,
    )


def _risk_list(risks: list[dict], height: int = 330) -> None:
    severity_class = {"高": "risk-high", "中": "risk-mid", "低": "risk-low"}
    items = []
    for risk in risks[:80]:
        severity = risk.get("severity", "低")
        items.append(
            '<div class="risk-item">'
            '<div class="risk-row">'
            f'<span class="risk-badge {severity_class.get(severity, "risk-low")}">{_html(severity)}</span>'
            f'<span class="risk-category">{_html(risk.get("category", "风险"))}</span>'
            "</div>"
            f'<div class="risk-path">{_html(risk.get("path", ""))}</div>'
            f'<div class="risk-message">{_html(risk.get("message", ""))}</div>'
            "</div>"
        )
    st.markdown(
        f'<div class="risk-scroll" style="max-height:{height}px;">{"".join(items)}</div>',
        unsafe_allow_html=True,
    )


def _ensure_project_dirs() -> None:
    ANALYZED_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "agent_logs").mkdir(parents=True, exist_ok=True)


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
        .scroll-title {
            display: block;
            overflow-x: auto;
            overflow-y: hidden;
            white-space: nowrap;
            scrollbar-width: thin;
            padding-bottom: 0.15rem;
        }
        .scroll-metric {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.7);
            border-radius: 8px;
            padding: 0.75rem 0.85rem;
            min-height: 96px;
        }
        .metric-label {
            color: #bfdbfe;
            font-size: 0.88rem;
            margin-bottom: 0.5rem;
        }
        .metric-value-x {
            color: #f8fafc;
            font-size: 1.42rem;
            font-weight: 700;
            line-height: 1.25;
            overflow-x: auto;
            overflow-y: hidden;
            white-space: nowrap;
            scrollbar-width: thin;
            padding-bottom: 0.2rem;
        }
        .tree-scroll {
            margin: 0;
            padding: 0.85rem;
            border-radius: 8px;
            background: rgba(2, 6, 23, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.18);
            color: #dbeafe;
            font-size: 0.82rem;
            line-height: 1.45;
            overflow-y: auto;
            overflow-x: hidden;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .risk-scroll {
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 8px;
            background: rgba(15, 23, 42, 0.48);
            padding: 0.65rem;
            overflow-y: auto;
            overflow-x: hidden;
        }
        .risk-item {
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            padding: 0.65rem 0.2rem;
        }
        .risk-item:last-child { border-bottom: none; }
        .risk-row { display: flex; gap: 0.45rem; align-items: center; margin-bottom: 0.35rem; }
        .risk-badge {
            border-radius: 8px;
            padding: 0.16rem 0.44rem;
            font-size: 0.74rem;
            font-weight: 800;
            color: #0f172a;
            flex: 0 0 auto;
        }
        .risk-high { background: #fb7185; }
        .risk-mid { background: #fbbf24; }
        .risk-low { background: #94a3b8; }
        .risk-category { color: #e0f2fe; font-weight: 700; font-size: 0.86rem; }
        .risk-path {
            color: #93c5fd;
            font-size: 0.78rem;
            word-break: break-all;
            margin-bottom: 0.25rem;
        }
        .risk-message {
            color: #cbd5e1;
            font-size: 0.86rem;
            line-height: 1.45;
            word-break: break-word;
        }
        .section-gap { height: 0.7rem; }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.7);
            border-radius: 8px;
            padding: 0.75rem 0.85rem;
        }
        div[data-testid="stMetricValue"] { color: #f8fafc; }
        div[data-testid="stMetricLabel"] { color: #bfdbfe; }
        button:disabled, button[disabled] {
            background: rgba(71, 85, 105, 0.72) !important;
            color: #cbd5e1 !important;
            border-color: rgba(148, 163, 184, 0.28) !important;
            cursor: not-allowed !important;
            opacity: 0.75 !important;
        }
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
