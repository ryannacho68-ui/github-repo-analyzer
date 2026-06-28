from __future__ import annotations

from src.rag_qa import answer_repository_question, retrieve_relevant_chunks


def test_keyword_rag_remains_available_when_chromadb_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPO_ANALYZER_DISABLE_CHROMA", "1")
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Demo\n\n## Install\npip install -r requirements.txt\n\n## Run\npython app.py\n",
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("streamlit>=1.35.0\n", encoding="utf-8")
    (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")

    chunks = retrieve_relevant_chunks("How do I run this project locally?", repo, top_k=3)

    assert chunks
    assert chunks[0]["retriever"] == "keyword"

    answer = answer_repository_question(
        "How do I run this project locally?",
        repo,
        {"tech_stack": {"frameworks": [], "tools": []}, "architecture": {}},
        use_llm=False,
    )

    assert answer["mode"] == "heuristic-runbook"
    assert answer["sources"]


def test_code_rag_prioritizes_file_and_function_hints(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPO_ANALYZER_DISABLE_CHROMA", "1")
    repo = tmp_path / "demo-repo"
    source_dir = repo / "src"
    source_dir.mkdir(parents=True)
    (repo / "README.md").write_text("# Demo\n\nA small auth service.\n", encoding="utf-8")
    (source_dir / "auth.py").write_text(
        "\n".join(
            [
                "import os",
                "",
                "def load_config():",
                "    return {'debug': True}",
                "",
                "def validate_token(token):",
                "    try:",
                "        return token == os.environ['API_TOKEN']",
                "    except:",
                "        return False",
            ]
        ),
        encoding="utf-8",
    )

    chunks = retrieve_relevant_chunks("src/auth.py 里的 validate_token 有没有问题？", repo, top_k=3)

    assert chunks
    assert chunks[0]["path"] == "src/auth.py"
    assert chunks[0]["chunk_type"] == "function"
    assert chunks[0]["symbol"] == "validate_token"


def test_code_review_template_uses_code_chunks_when_llm_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPO_ANALYZER_DISABLE_CHROMA", "1")
    repo = tmp_path / "demo-repo"
    source_dir = repo / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "runner.py").write_text(
        "\n".join(
            [
                "import subprocess",
                "",
                "def run_command(command):",
                "    return subprocess.check_output(command, shell=True)",
            ]
        ),
        encoding="utf-8",
    )

    answer = answer_repository_question(
        "请检查 src/runner.py 的 run_command 是否有安全问题",
        repo,
        {"tech_stack": {}, "architecture": {}},
        use_llm=False,
    )

    assert answer["mode"] == "retrieval-template"
    assert "代码审查线索" in answer["answer"]
    assert "shell=True" in answer["answer"]
    assert answer["sources"][0]["chunk_type"] == "function"
