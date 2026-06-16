from __future__ import annotations

from types import SimpleNamespace

from src import orchestrator


def test_single_repository_analysis_smoke(tmp_path, monkeypatch):
    repo_path = _make_repo(tmp_path, "repo-a")
    _patch_loader(monkeypatch, repo_path, "repo-a")

    result = orchestrator.analyze_repository(
        "https://github.com/demo/repo-a",
        tmp_path,
        use_llm=False,
        model="qwen2.5:1.5b",
    )

    assert result["repo_info"]["name"] == "repo-a"
    assert len(result["dimension_scores"]) == 10
    assert result["project_overview"]["evidence"]
    assert any(item["agent_name"] == "项目概览 Agent" for item in result["agent_logs"])
    assert any(item["agent_name"] == "技术栈 Agent" for item in result["agent_logs"])


def test_compare_repositories_smoke(tmp_path, monkeypatch):
    repo_a = _make_repo(tmp_path, "repo-a")
    repo_b = _make_repo(tmp_path, "repo-b")
    calls = {"count": 0}

    def fake_fetch(repo_url):
        name = repo_url.rstrip("/").split("/")[-1]
        return {
            "repo": {"description": f"{name} demo repository", "topics": ["demo", "python"]},
            "readme": {"available": True, "excerpt": f"# {name}\nA small Flask demo."},
        }

    def fake_clone(repo_url, base_dir, refresh=False):
        calls["count"] += 1
        path = repo_a if calls["count"] == 1 else repo_b
        name = path.name
        return SimpleNamespace(
            to_dict=lambda: {
                "name": name,
                "owner": "demo",
                "safe_name": f"demo_{name}",
                "web_url": f"https://github.com/demo/{name}",
                "clone_url": f"https://github.com/demo/{name}.git",
                "local_path": str(path),
                "source": "test",
                "size_kb": 1,
            }
        )

    monkeypatch.setattr(orchestrator, "fetch_github_api_snapshot", fake_fetch)
    monkeypatch.setattr(orchestrator, "clone_or_use_cache", fake_clone)

    result = orchestrator.compare_repositories(
        "https://github.com/demo/repo-a",
        "https://github.com/demo/repo-b",
        tmp_path,
        use_llm=False,
        model="qwen2.5:1.5b",
    )

    comparison = result["comparison"]
    assert len(comparison["dimension_comparison"]) == 10
    assert comparison["markdown_report"].startswith("# 仓库对比分析报告")
    assert comparison["agent_logs"][0]["agent_name"] == "对比 Agent"


def _patch_loader(monkeypatch, repo_path, name):
    monkeypatch.setattr(
        orchestrator,
        "fetch_github_api_snapshot",
        lambda repo_url: {
            "repo": {"description": f"{name} demo repository", "topics": ["demo", "python"]},
            "readme": {"available": True, "excerpt": f"# {name}\nA small Flask demo."},
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "clone_or_use_cache",
        lambda repo_url, base_dir, refresh=False: SimpleNamespace(
            to_dict=lambda: {
                "name": name,
                "owner": "demo",
                "safe_name": f"demo_{name}",
                "web_url": f"https://github.com/demo/{name}",
                "clone_url": f"https://github.com/demo/{name}.git",
                "local_path": str(repo_path),
                "source": "test",
                "size_kb": 1,
            }
        ),
    )


def _make_repo(tmp_path, name):
    repo = tmp_path / name
    repo.mkdir()
    (repo / "README.md").write_text(
        f"# {name}\n\nA small Flask demo app for testing repository analysis.\n\n## Install\npip install -r requirements.txt\n\n## Run\npython app.py\n",
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("flask==3.0.0\npytest==8.0.0\n", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n.env\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "from flask import Flask\n\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    return 'ok'\n",
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    return repo
