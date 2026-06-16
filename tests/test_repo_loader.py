import pytest
import stat

from src.repo_loader import RepoLoadError, _remove_cached_repo, parse_github_url


def test_parse_https_github_url_normalizes_reference():
    reference = parse_github_url("https://github.com/streamlit/streamlit-hello.git")

    assert reference.owner == "streamlit"
    assert reference.name == "streamlit-hello"
    assert reference.safe_name == "streamlit_streamlit-hello"
    assert reference.clone_url == "https://github.com/streamlit/streamlit-hello.git"


def test_parse_ssh_github_url():
    reference = parse_github_url("git@github.com:pallets/flask.git")

    assert reference.owner == "pallets"
    assert reference.name == "flask"
    assert reference.web_url == "https://github.com/pallets/flask"


def test_parse_non_github_url_rejected():
    with pytest.raises(RepoLoadError):
        parse_github_url("https://example.com/org/repo")


def test_remove_cached_repo_handles_readonly_git_pack(tmp_path):
    repo_dir = tmp_path / "owner_repo"
    pack_dir = repo_dir / ".git" / "objects" / "pack"
    pack_dir.mkdir(parents=True)
    pack_file = pack_dir / "pack-demo.idx"
    pack_file.write_text("demo", encoding="utf-8")
    pack_file.chmod(stat.S_IREAD)

    _remove_cached_repo(repo_dir, tmp_path)

    assert not repo_dir.exists()
