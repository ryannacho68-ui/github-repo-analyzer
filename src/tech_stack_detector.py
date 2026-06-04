from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


EXTENSION_LANGUAGE_MAP = {
    ".py": "Python",
    ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".scala": "Scala",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".ps1": "PowerShell",
}

PYTHON_FRAMEWORKS = {
    "streamlit": "Streamlit",
    "flask": "Flask",
    "django": "Django",
    "fastapi": "FastAPI",
    "gradio": "Gradio",
    "pandas": "pandas",
    "numpy": "NumPy",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
    "sklearn": "scikit-learn",
    "scikit-learn": "scikit-learn",
    "pytest": "pytest",
}

NODE_FRAMEWORKS = {
    "react": "React",
    "vue": "Vue",
    "next": "Next.js",
    "next.js": "Next.js",
    "nuxt": "Nuxt",
    "express": "Express",
    "koa": "Koa",
    "vite": "Vite",
    "webpack": "Webpack",
    "svelte": "Svelte",
    "@angular/core": "Angular",
}


def detect_tech_stack(repo_path: Path, file_analysis: dict | None = None) -> dict:
    repo_path = Path(repo_path)
    frameworks: set[str] = set()
    tools: set[str] = set()
    indicators: list[str] = []
    dependencies: dict[str, list[str]] = {}
    dependency_versions: dict[str, list[str]] = {}

    extension_counts = (file_analysis or {}).get("extension_counts", {})
    language_counts = _language_counts(extension_counts)
    main_language = max(language_counts, key=language_counts.get) if language_counts else "Unknown"

    requirements_path = repo_path / "requirements.txt"
    if requirements_path.exists():
        python_deps = _parse_requirements(requirements_path)
        dependency_versions["python"] = _parse_requirements_with_versions(requirements_path)
        dependencies["python"] = python_deps
        tools.add("pip")
        indicators.append("requirements.txt")
        frameworks.update(_match_frameworks(python_deps, PYTHON_FRAMEWORKS))

    pyproject_path = repo_path / "pyproject.toml"
    if pyproject_path.exists():
        pyproject_deps, pyproject_tools = _parse_pyproject(pyproject_path)
        dependencies.setdefault("python", [])
        dependencies["python"] = sorted(set(dependencies["python"] + pyproject_deps))
        tools.update(pyproject_tools or {"pyproject"})
        indicators.append("pyproject.toml")
        frameworks.update(_match_frameworks(pyproject_deps, PYTHON_FRAMEWORKS))

    setup_path = repo_path / "setup.py"
    if setup_path.exists():
        tools.add("setuptools")
        indicators.append("setup.py")

    package_path = repo_path / "package.json"
    if package_path.exists():
        node_deps, node_tools, node_versions = _parse_package_json(package_path)
        dependencies["node"] = node_deps
        dependency_versions["node"] = node_versions
        tools.update(node_tools or {"npm"})
        indicators.append("package.json")
        frameworks.update(_match_frameworks(node_deps, NODE_FRAMEWORKS))

    if (repo_path / "pom.xml").exists():
        tools.add("Maven")
        indicators.append("pom.xml")
        dependencies["java"] = _parse_text_dependencies(repo_path / "pom.xml", r"<artifactId>(.*?)</artifactId>")
        if _file_contains(repo_path / "pom.xml", "spring-boot"):
            frameworks.add("Spring Boot")

    if (repo_path / "build.gradle").exists() or (repo_path / "build.gradle.kts").exists():
        tools.add("Gradle")
        indicators.append("build.gradle")
        gradle_file = repo_path / "build.gradle"
        if not gradle_file.exists():
            gradle_file = repo_path / "build.gradle.kts"
        if _file_contains(gradle_file, "springframework"):
            frameworks.add("Spring")

    if (repo_path / "Dockerfile").exists():
        tools.add("Docker")
        indicators.append("Dockerfile")
    if (repo_path / "docker-compose.yml").exists() or (repo_path / "docker-compose.yaml").exists():
        tools.add("Docker Compose")
        indicators.append("docker-compose.yml")
    if (repo_path / ".github" / "workflows").exists():
        tools.add("GitHub Actions")
        indicators.append(".github/workflows")

    return {
        "main_language": main_language,
        "languages": _format_languages(language_counts),
        "frameworks": sorted(frameworks),
        "dependencies": dependencies,
        "dependency_versions": dependency_versions,
        "tools": sorted(tools),
        "indicators": indicators,
    }


def _language_counts(extension_counts: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for extension, count in extension_counts.items():
        language = EXTENSION_LANGUAGE_MAP.get(extension)
        if language:
            counts[language] = counts.get(language, 0) + int(count)
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))


def _format_languages(language_counts: dict[str, int]) -> list[dict]:
    total = sum(language_counts.values())
    return [
        {
            "language": language,
            "files": count,
            "ratio": round(count / total * 100, 2) if total else 0,
        }
        for language, count in language_counts.items()
    ]


def _parse_requirements(path: Path) -> list[str]:
    deps: list[str] = []
    for line in _read_text(path).splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or clean.startswith("-"):
            continue
        package = re.split(r"[<>=~!;\[]", clean, maxsplit=1)[0].strip()
        if package:
            deps.append(package)
    return sorted(set(deps), key=str.lower)


def _parse_requirements_with_versions(path: Path) -> list[str]:
    specs: list[str] = []
    for line in _read_text(path).splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or clean.startswith("-"):
            continue
        specs.append(clean)
    return sorted(set(specs), key=str.lower)[:120]


def _parse_pyproject(path: Path) -> tuple[list[str], set[str]]:
    deps: list[str] = []
    tools: set[str] = set()
    try:
        data = tomllib.loads(_read_text(path))
    except Exception:
        return deps, {"pyproject"}

    project = data.get("project", {})
    for item in project.get("dependencies", []) or []:
        package = re.split(r"[<>=~!;\[]", str(item), maxsplit=1)[0].strip()
        if package:
            deps.append(package)

    poetry = data.get("tool", {}).get("poetry", {})
    if poetry:
        tools.add("Poetry")
        for package in poetry.get("dependencies", {}).keys():
            if package.lower() != "python":
                deps.append(package)

    tool_section = data.get("tool", {})
    for tool_name in ("ruff", "black", "pytest", "mypy", "poetry", "hatch"):
        if tool_name in tool_section:
            tools.add(tool_name)

    return sorted(set(deps), key=str.lower), tools


def _parse_package_json(path: Path) -> tuple[list[str], set[str], list[str]]:
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError:
        return [], {"npm"}, []

    deps = set()
    version_specs = []
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(field) or {}
        deps.update(section.keys())
        version_specs.extend(f"{name}@{version}" for name, version in section.items())

    scripts = data.get("scripts") or {}
    tools = {"npm"}
    if (path.parent / "pnpm-lock.yaml").exists():
        tools.add("pnpm")
    if (path.parent / "yarn.lock").exists():
        tools.add("Yarn")
    if any("vite" in str(value) for value in scripts.values()):
        tools.add("Vite")

    return sorted(deps, key=str.lower), tools, sorted(version_specs, key=str.lower)[:160]


def _parse_text_dependencies(path: Path, pattern: str) -> list[str]:
    return sorted(set(re.findall(pattern, _read_text(path), flags=re.IGNORECASE)))[:80]


def _match_frameworks(dependencies: list[str], framework_map: dict[str, str]) -> set[str]:
    matches = set()
    lower_deps = {dep.lower(): dep for dep in dependencies}
    for key, label in framework_map.items():
        if key.lower() in lower_deps:
            matches.add(label)
    return matches


def _file_contains(path: Path, text: str) -> bool:
    return text.lower() in _read_text(path).lower()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
