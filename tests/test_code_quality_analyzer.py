from src.code_quality_analyzer import analyze_code_quality


def test_code_quality_detects_pytest_files(tmp_path):
    package_dir = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    package_dir.mkdir()
    tests_dir.mkdir()
    (package_dir / "sample.py").write_text(
        "def add(left, right):\n"
        "    return left + right\n",
        encoding="utf-8",
    )
    (tests_dir / "test_sample.py").write_text(
        "from src.sample import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    result = analyze_code_quality(tmp_path)

    assert result["tests"]["has_tests"] is True
    assert "tests" in result["tests"]["test_dirs"]
    assert "tests/test_sample.py" in result["tests"]["test_files"]
    assert not any("未检测到 Python 测试目录" in item for item in result["deductions"])
