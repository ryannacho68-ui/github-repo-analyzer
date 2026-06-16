from src.agents.comparison_agent import ComparisonAgent
from src.agents.summary_agent import DIMENSIONS


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
