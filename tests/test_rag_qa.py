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
