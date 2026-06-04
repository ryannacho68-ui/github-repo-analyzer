from types import SimpleNamespace

from src.github_api_client import _github_headers, _is_rate_limited, _rate_limit_message


def test_github_headers_include_optional_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "example-token-for-test")

    headers = _github_headers()

    assert headers["Authorization"] == "Bearer example-token-for-test"
    assert headers["User-Agent"] == "github-repo-analyzer-course-design"


def test_rate_limit_response_is_detected():
    response = SimpleNamespace(
        status_code=403,
        headers={"X-RateLimit-Remaining": "0"},
        text="rate limit exceeded",
    )
    response.json = lambda: {"message": "API rate limit exceeded"}

    assert _is_rate_limited(response) is True
    assert "已降级为 git clone + 本地静态分析" in _rate_limit_message(response, "获取仓库信息")
