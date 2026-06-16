from src.agents.comparison_agent import ComparisonAgent
from src.agents.base_agent import BaseAgent
from src.agents.summary_agent import DIMENSIONS
from src.agents.summary_agent import SummaryAgent
from src.analysis_models import AgentResult, RepositoryContext


class DummyAgent(BaseAgent):
    name = "Dummy Agent"

    def analyze(self, context, shared):
        raise NotImplementedError


class FakeLLMClient:
    def __init__(self):
        self.called = False

    def generate_json(self, system_prompt, user_prompt, fallback):
        self.called = True
        return {
            **fallback,
            "final_summary": "demo/repo 汇总完成。",
            "strengths": [{"name": "结构清晰", "evidence": "目录分层"}],
            "issues": [{"name": "测试不足", "evidence": "测试评分偏低"}],
            "improvement_suggestions": [{"action": "补充测试"}],
            "_llm_meta": {
                "llm_used": True,
                "model": "fake-llm",
                "status": "ok",
                "error_message": "",
            },
        }


def test_dimension_contract_contains_ten_dimensions():
    assert DIMENSIONS == [
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


def test_comparison_agent_compares_dimension_scores_without_llm():
    repo_a = {
        "repo_info": {"name": "repo-a", "owner": "demo", "web_url": "https://github.com/demo/repo-a"},
        "project_overview": {"project_type": "Web 应用"},
        "dimension_scores": {"项目概览": 8, "技术栈识别": 7, "部署方式": 4, "潜在问题": 8},
        "final_summary": {"overall_score": 7.0, "strengths": ["文档较完整"], "suggestions": ["补充 Dockerfile"]},
    }
    repo_b = {
        "repo_info": {"name": "repo-b", "owner": "demo", "web_url": "https://github.com/demo/repo-b"},
        "project_overview": {"project_type": "CLI 工具"},
        "dimension_scores": {"项目概览": 6, "技术栈识别": 8, "部署方式": 7, "潜在问题": 6},
        "final_summary": {"overall_score": 6.8, "strengths": ["部署更完整"], "suggestions": ["补充 README"]},
    }

    result = ComparisonAgent().analyze(repo_a, repo_b).to_dict()

    assert result["repo_a"]["name"] == "repo-a"
    assert result["winner_by_dimension"]["项目概览"].startswith("A:")
    assert result["winner_by_dimension"]["部署方式"].startswith("B:")
    assert "learning" in result["scenario_recommendations"]
    assert result["agent_logs"][0]["llm_used"] is False


def test_base_agent_normalizes_non_list_outputs():
    result = DummyAgent().build_result(
        summary="ok",
        findings={"language": "Python"},
        evidence={"file_tree_excerpt": "repo/"},
        score=8,
        suggestions={"next": "Add docs"},
    )

    assert result.findings == ['language: "Python"']
    assert result.evidence == [{"type": "file_tree_excerpt", "value": "repo/"}]
    assert result.suggestions == ['next: "Add docs"']


def test_summary_agent_handles_dict_evidence_and_uses_llm(tmp_path):
    context = RepositoryContext(
        repo_name="repo",
        owner="demo",
        url="https://github.com/demo/repo",
        local_path=str(tmp_path),
    )
    tech_result = AgentResult(
        agent_name="技术栈 Agent",
        summary="Python 技术栈",
        findings=["主要语言：Python"],
        evidence={"file_tree_excerpt": "repo/"},
        score=8,
        suggestions={"next": "补充依赖版本"},
        confidence="high",
    )
    client = FakeLLMClient()
    shared = {
        "agent_results": {"技术栈 Agent": tech_result},
        "llm_client": client,
        "file_tree": {"total_files": 3, "total_code_lines": 20},
        "test_deploy": {"tests": {"score": 0, "test_file_count": 0}, "deployment": {"score": 0}},
        "dependency_health": {"score": 6},
        "risks": {"score": 80},
    }

    result = SummaryAgent().analyze(context, shared)

    assert client.called is True
    assert result.llm_used is True
    assert result.status == "ok"
    assert result.score > 0
