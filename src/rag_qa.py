from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

import requests

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

from .file_tree import IGNORED_DIRS
from .llm_reporter import DEFAULT_ENDPOINT, DEFAULT_MODEL, list_available_models

CHROMA_COLLECTION_PREFIX = "repo_rag"
CHROMA_DB_DIR = Path(
    os.environ.get(
        "GITHUB_REPO_ANALYZER_CHROMA_DIR",
        Path(__file__).resolve().parents[1] / "data" / "chroma_rag",
    )
)
CHROMA_EMBEDDING_DIMENSIONS = 384
CHROMA_MAX_CHUNKS = 1500
CHROMA_BATCH_SIZE = 128


TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ini",
    ".cfg",
    ".html",
    ".css",
}

RUN_KEYWORDS = {
    "run",
    "start",
    "serve",
    "dev",
    "install",
    "quickstart",
    "usage",
    "启动",
    "运行",
    "安装",
    "本地",
    "开发",
}

COMMAND_HINT_RE = re.compile(
    r"\b("
    r"pip install|python -m|python [\w./-]+\.py|streamlit run|flask run|uvicorn "
    r"|fastapi dev|django-admin|python manage\.py|npm install|npm run|npm start"
    r"|pnpm install|pnpm run|yarn install|yarn start|docker compose|docker-compose\s+|docker build"
    r"|poetry install|poetry run|uv sync|uv run|pytest|make "
    r")",
    re.IGNORECASE,
)
COMMAND_PREFIX_RE = re.compile(
    r"^("
    r"pip install|python -m|python [\w./-]+\.py|streamlit run|flask run|uvicorn "
    r"|fastapi dev|python manage\.py|npm install|npm run|npm start"
    r"|pnpm install|pnpm run|pnpm dev|pnpm start|yarn install|yarn start|yarn dev"
    r"|docker compose|docker-compose\s+|docker build|poetry install|poetry run"
    r"|uv sync|uv run|pytest|make "
    r")",
    re.IGNORECASE,
)


def answer_repository_question(
    question: str,
    repo_path: Path,
    analysis: dict[str, Any],
    model: str = DEFAULT_MODEL,
    use_llm: bool = True,
    endpoint: str = DEFAULT_ENDPOINT,
) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {"answer": "请输入问题后再检索。", "sources": [], "mode": "empty", "message": ""}

    repo_path = Path(repo_path)
    chunks = retrieve_relevant_chunks(question, repo_path, top_k=8)
    heuristic = _heuristic_answer(question, repo_path, analysis, chunks)
    if heuristic:
        return heuristic

    if use_llm and chunks:
        available_models = list_available_models(timeout=2)
        if not available_models or model in available_models:
            try:
                prompt = _build_qa_prompt(question, analysis, chunks)
                response = requests.post(
                    endpoint,
                    json={
                        "model": model or DEFAULT_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                    timeout=60,
                )
                response.raise_for_status()
                answer = (response.json().get("response") or "").strip()
                if answer:
                    return {
                        "answer": answer,
                        "sources": _source_rows(chunks),
                        "mode": "ollama-rag",
                        "message": "已基于检索片段调用 Ollama 回答。",
                    }
            except Exception:
                pass

    return {
        "answer": _template_qa_answer(question, chunks),
        "sources": _source_rows(chunks),
        "mode": "retrieval-template",
        "message": "LLM 未启用或不可用，已返回基于检索片段的模板回答。",
    }


def retrieve_relevant_chunks(question: str, repo_path: Path, top_k: int = 6) -> list[dict[str, Any]]:
    chroma_chunks = _retrieve_chromadb_chunks(question, repo_path, top_k)
    if chroma_chunks:
        return chroma_chunks
    return _retrieve_keyword_chunks(question, repo_path, top_k)


def _retrieve_keyword_chunks(question: str, repo_path: Path, top_k: int = 6) -> list[dict[str, Any]]:
    query_tokens = _tokenize(question)
    is_run_question = _is_run_question(question)
    if is_run_question:
        query_tokens |= RUN_KEYWORDS
    if not query_tokens:
        return []

    scored_chunks = []
    for path in _iter_text_files(repo_path):
        rel_path = path.relative_to(repo_path).as_posix()
        text = _read_text(path)
        if not text:
            continue
        for chunk in _chunk_text(text, rel_path):
            chunk_tokens = _tokenize(chunk["content"] + " " + rel_path)
            overlap = query_tokens & chunk_tokens
            score = len(overlap) * 4 + sum(1 for token in query_tokens if token in rel_path.lower())
            if is_run_question:
                score += _run_chunk_bonus(rel_path, chunk["content"])
            if any(token in rel_path.lower() for token in {"readme", "config", "model", "route", "database"}):
                score += 1
            if score <= 0:
                continue
            chunk["score"] = score
            chunk["retriever"] = "keyword"
            scored_chunks.append(chunk)

    return sorted(scored_chunks, key=lambda item: item["score"], reverse=True)[:top_k]


def _retrieve_chromadb_chunks(question: str, repo_path: Path, top_k: int = 6) -> list[dict[str, Any]]:
    if not _is_chromadb_enabled():
        return []

    query = (question or "").strip()
    if not query:
        return []

    chromadb = _load_chromadb()
    if chromadb is None:
        return []

    try:
        repo_path = Path(repo_path)
        chunks = _collect_rag_chunks(repo_path)
        if not chunks:
            return []

        CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        collection_name = _chroma_collection_name(repo_path)
        collection = _ensure_chroma_collection(client, collection_name, chunks)

        result = collection.query(
            query_embeddings=[_hash_embedding(query)],
            n_results=min(top_k, len(chunks)),
            include=["documents", "metadatas", "distances"],
        )
        return _chroma_query_to_chunks(result)
    except Exception:
        return []


def _is_chromadb_enabled() -> bool:
    flag = os.environ.get("GITHUB_REPO_ANALYZER_DISABLE_CHROMA", "")
    return flag.strip().lower() not in {"1", "true", "yes", "on"}


def _load_chromadb():
    try:
        import chromadb
    except Exception:
        return None
    return chromadb


def _ensure_chroma_collection(client: Any, collection_name: str, chunks: list[dict[str, Any]]) -> Any:
    signature = _corpus_signature(chunks)
    manifest = _read_chroma_manifest(collection_name)

    try:
        collection = client.get_or_create_collection(name=collection_name)
        if (
            manifest.get("signature") == signature
            and manifest.get("chunk_count") == len(chunks)
            and collection.count() == len(chunks)
        ):
            return collection
        client.delete_collection(name=collection_name)
    except Exception:
        try:
            client.delete_collection(name=collection_name)
        except Exception:
            pass

    collection = client.create_collection(name=collection_name)
    _index_chroma_chunks(collection, chunks)
    _write_chroma_manifest(collection_name, {"signature": signature, "chunk_count": len(chunks)})
    return collection


def _index_chroma_chunks(collection: Any, chunks: list[dict[str, Any]]) -> None:
    for start in range(0, len(chunks), CHROMA_BATCH_SIZE):
        batch = chunks[start : start + CHROMA_BATCH_SIZE]
        collection.add(
            ids=[item["id"] for item in batch],
            documents=[item["content"] for item in batch],
            metadatas=[
                {
                    "path": item["path"],
                    "start_line": int(item["start_line"]),
                    "end_line": int(item["end_line"]),
                }
                for item in batch
            ],
            embeddings=[_hash_embedding(_chunk_embedding_text(item)) for item in batch],
        )


def _collect_rag_chunks(repo_path: Path, max_chunks: int = CHROMA_MAX_CHUNKS) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    paths = sorted(_iter_text_files(repo_path), key=lambda item: item.relative_to(repo_path).as_posix().lower())
    for path in paths:
        rel_path = path.relative_to(repo_path).as_posix()
        text = _read_text(path)
        if not text:
            continue
        for chunk in _chunk_text(text, rel_path):
            chunk["id"] = _chunk_id(chunk)
            chunks.append(chunk)
            if len(chunks) >= max_chunks:
                return chunks
    return chunks


def _chroma_query_to_chunks(result: dict[str, Any]) -> list[dict[str, Any]]:
    documents = _first_result_list(result.get("documents"))
    metadatas = _first_result_list(result.get("metadatas"))
    distances = _first_result_list(result.get("distances"))
    chunks = []

    for index, document in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
        path = str(metadata.get("path") or "")
        if not path:
            continue
        distance = distances[index] if index < len(distances) else None
        chunks.append(
            {
                "path": path,
                "start_line": _as_int(metadata.get("start_line"), 1),
                "end_line": _as_int(metadata.get("end_line"), 1),
                "content": document or "",
                "score": _distance_to_score(distance),
                "retriever": "chromadb",
            }
        )
    return chunks


def _first_result_list(value: Any) -> list[Any]:
    if isinstance(value, list) and value:
        first = value[0]
        return first if isinstance(first, list) else value
    return []


def _distance_to_score(distance: Any) -> float:
    try:
        numeric = max(float(distance), 0.0)
    except (TypeError, ValueError):
        return 0.0
    return round(1.0 / (1.0 + numeric), 4)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _chroma_collection_name(repo_path: Path) -> str:
    digest = hashlib.sha1(str(repo_path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{CHROMA_COLLECTION_PREFIX}_{digest}"


def _manifest_path(collection_name: str) -> Path:
    return CHROMA_DB_DIR / f"{collection_name}.json"


def _read_chroma_manifest(collection_name: str) -> dict[str, Any]:
    path = _manifest_path(collection_name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_chroma_manifest(collection_name: str, manifest: dict[str, Any]) -> None:
    try:
        _manifest_path(collection_name).write_text(json.dumps(manifest), encoding="utf-8")
    except OSError:
        pass


def _corpus_signature(chunks: list[dict[str, Any]]) -> str:
    digest = hashlib.sha1()
    for chunk in chunks:
        digest.update(chunk["id"].encode("utf-8", errors="ignore"))
        digest.update(str(len(chunk["content"])).encode("ascii"))
        digest.update(hashlib.sha1(chunk["content"].encode("utf-8", errors="ignore")).digest())
    return digest.hexdigest()


def _chunk_id(chunk: dict[str, Any]) -> str:
    raw = f"{chunk['path']}:{chunk['start_line']}:{chunk['end_line']}"
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()
    return f"chunk_{digest}"


def _chunk_embedding_text(chunk: dict[str, Any]) -> str:
    return f"{chunk['path']}\n{chunk['content']}"


def _hash_embedding(text: str) -> list[float]:
    vector = [0.0] * CHROMA_EMBEDDING_DIMENSIONS
    terms = _embedding_terms(text)
    if not terms:
        return vector

    for term in terms[:4000]:
        digest = hashlib.blake2b(term.encode("utf-8", errors="ignore"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % CHROMA_EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _embedding_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{2,}", text.lower()):
        terms.append(token)
        if "_" in token:
            terms.extend(part for part in token.split("_") if len(part) > 1)
        if token.isascii() and len(token) > 5:
            terms.extend(token[index : index + 4] for index in range(0, len(token) - 3))
    return terms


def _heuristic_answer(
    question: str,
    repo_path: Path,
    analysis: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lower = question.lower()
    if _is_overview_question(question):
        overview = analysis.get("project_overview") or {}
        if overview:
            lines = [
                f"这个仓库的项目类型是：{overview.get('project_type', '通用代码仓库')}。",
                f"项目用途：{overview.get('purpose', '暂未识别到明确用途。')}",
                f"目标用户：{overview.get('target_users', '开发者')}",
                f"判断置信度：{overview.get('confidence', 0)}/100",
            ]
            evidence = overview.get("evidence") or []
            if evidence:
                lines.append("")
                lines.append("主要依据：")
                for item in evidence[:5]:
                    lines.append(f"- {item.get('source')}: {item.get('text')}")
            return {
                "answer": "\n".join(lines),
                "sources": [
                    {"path": item.get("source", "project_overview"), "line_range": "-", "score": overview.get("confidence", 0)}
                    for item in evidence[:5]
                ],
                "mode": "heuristic-overview",
                "message": "已基于 GitHub 描述、README、元信息和技术栈生成项目内容概览。",
            }

    if any(word in lower for word in ["数据库模型", "database model", "models", "表结构"]):
        models = _extract_python_models(repo_path)
        if models:
            lines = ["项目中检测到以下疑似数据库/实体模型："]
            for index, model in enumerate(models, start=1):
                fields = ", ".join(model["fields"][:12]) or "未识别到字段"
                lines.append(f"{index}. {model['class']}（{model['path']}）：字段包括 {fields}")
            return {
                "answer": "\n".join(lines),
                "sources": [{"path": item["path"], "line": item["line"]} for item in models],
                "mode": "heuristic-models",
                "message": "已通过 Python AST 和 SQLAlchemy/Django 模型特征回答。",
            }

    if _is_run_question(question):
        return {
            "answer": _local_run_answer(repo_path, analysis, chunks),
            "sources": _source_rows(chunks),
            "mode": "heuristic-runbook",
            "message": "已结合 README、依赖文件、脚本配置、入口文件和环境变量引用生成运行建议。",
        }
    return None


def _extract_python_models(repo_path: Path) -> list[dict[str, Any]]:
    models = []
    for path in _iter_text_files(repo_path):
        if path.suffix.lower() != ".py":
            continue
        text = _read_text(path)
        if not any(marker in text for marker in ["db.Model", "models.Model", "SQLModel", "DeclarativeBase", "Column("]):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            fields = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.append(item.target.id)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            fields.append(target.id)
            if fields or _class_inherits_model(node):
                models.append(
                    {
                        "class": node.name,
                        "path": path.relative_to(repo_path).as_posix(),
                        "line": node.lineno,
                        "fields": sorted(set(fields)),
                    }
                )
    return models[:20]


def _class_inherits_model(node: ast.ClassDef) -> bool:
    base_names = []
    for base in node.bases:
        if isinstance(base, ast.Attribute):
            base_names.append(base.attr)
        elif isinstance(base, ast.Name):
            base_names.append(base.id)
    return any(name.lower() in {"model", "sqlmodel", "base"} for name in base_names)


def _local_run_answer(repo_path: Path, analysis: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    tech = analysis.get("tech_stack") or {}
    architecture = analysis.get("architecture") or {}
    frameworks = set(tech.get("frameworks") or [])
    tools = set(tech.get("tools") or [])

    steps: list[dict[str, str]] = []
    steps.extend(_readme_command_steps(repo_path))
    steps.extend(_dependency_install_steps(repo_path, tools))
    steps.extend(_package_script_steps(repo_path))
    steps.extend(_pyproject_script_steps(repo_path))
    steps.extend(_framework_run_steps(repo_path, frameworks, architecture))
    steps.extend(_docker_steps(repo_path, tools))

    deduped_steps = _dedupe_steps(steps)
    env_vars = _find_env_vars(repo_path)
    entry_points = architecture.get("entry_points") or _guess_entry_points(repo_path)

    answer = ["根据 README、依赖文件、脚本配置和代码特征，建议按以下方式本地运行："]
    if deduped_steps:
        for index, item in enumerate(deduped_steps[:10], start=1):
            source = f"（依据：{item['source']}）" if item.get("source") else ""
            answer.append(f"{index}. `{item['command']}` {source}".rstrip())
    else:
        if (repo_path / "SKILL.md").exists():
            answer.append("1. 这个仓库更像 skill/文档/脚本型仓库，不是一个需要启动 Web 服务的应用。")
            answer.append("2. 建议先阅读 `README.md` 和 `SKILL.md`，再按其中说明使用。")
            scripts = _script_files(repo_path)
            if scripts:
                answer.append(f"3. 可关注脚本文件：{', '.join(scripts[:8])}。")
        elif (repo_path / "README.md").exists() or (repo_path / "readme.md").exists():
            answer.append("1. README 中没有抽取到明确启动命令，建议先按 README 的安装/使用章节操作。")
        else:
            answer.append("1. 先安装依赖：如果是 Python 项目通常执行 `pip install -e .`；如果是 Node 项目通常执行 `npm install`。")
        if entry_points:
            answer.append(f"2. 仓库疑似入口文件：{', '.join(entry_points[:5])}，建议从这些文件确认启动命令。")
        elif not (repo_path / "SKILL.md").exists():
            answer.append("2. 暂未识别到明确入口文件，建议先查看 README、Makefile、package.json 或 pyproject.toml。")

    if entry_points:
        answer.append("")
        answer.append("疑似入口文件：")
        answer.append(", ".join(entry_points[:8]))

    if env_vars:
        answer.append("")
        answer.append("运行前可能需要配置的环境变量：")
        answer.append(", ".join(env_vars[:20]))

    readme_notes = _readme_run_notes(repo_path)
    if readme_notes:
        answer.append("")
        answer.append("README 中与运行相关的原文线索：")
        answer.extend(f"- {note}" for note in readme_notes[:5])

    if chunks:
        answer.append("")
        answer.append("检索来源已列在下方，可展开核对具体文件片段。")
    return "\n".join(answer)


def _readme_command_steps(repo_path: Path) -> list[dict[str, str]]:
    steps = []
    for path in _readme_paths(repo_path):
        text = _read_text(path)
        for command in _extract_shell_commands(text):
            if _looks_like_run_command(command):
                steps.append({"command": command, "source": path.name})
    return steps[:12]


def _dependency_install_steps(repo_path: Path, tools: set[str]) -> list[dict[str, str]]:
    steps = []
    if (repo_path / "requirements.txt").exists():
        steps.append({"command": "pip install -r requirements.txt", "source": "requirements.txt"})
    if (repo_path / "pyproject.toml").exists():
        if "Poetry" in tools:
            steps.append({"command": "poetry install", "source": "pyproject.toml"})
        elif "hatch" in tools:
            steps.append({"command": "pip install -e .", "source": "pyproject.toml"})
        else:
            steps.append({"command": "pip install -e .", "source": "pyproject.toml"})
    if (repo_path / "setup.py").exists() or (repo_path / "setup.cfg").exists():
        steps.append({"command": "pip install -e .", "source": "setup.py/setup.cfg"})
    if (repo_path / "package.json").exists():
        if (repo_path / "pnpm-lock.yaml").exists():
            steps.append({"command": "pnpm install", "source": "pnpm-lock.yaml"})
        elif (repo_path / "yarn.lock").exists():
            steps.append({"command": "yarn install", "source": "yarn.lock"})
        else:
            steps.append({"command": "npm install", "source": "package.json"})
    return steps


def _package_script_steps(repo_path: Path) -> list[dict[str, str]]:
    path = repo_path / "package.json"
    if not path.exists():
        return []
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError:
        return []
    scripts = data.get("scripts") or {}
    preferred = ["dev", "start", "serve", "preview", "build", "test"]
    package_manager = "pnpm" if (repo_path / "pnpm-lock.yaml").exists() else "yarn" if (repo_path / "yarn.lock").exists() else "npm"
    steps = []
    for name in preferred:
        if name in scripts:
            command = f"{package_manager} {'run ' if package_manager == 'npm' and name not in {'start', 'test'} else ''}{name}"
            if package_manager in {"pnpm", "yarn"} and name not in {"start", "test"}:
                command = f"{package_manager} {name}"
            steps.append({"command": command, "source": f"package.json scripts.{name} = {scripts[name]}"})
    return steps


def _pyproject_script_steps(repo_path: Path) -> list[dict[str, str]]:
    path = repo_path / "pyproject.toml"
    if not path.exists():
        return []
    try:
        data = tomllib.loads(_read_text(path))
    except Exception:
        return []
    scripts = (data.get("project") or {}).get("scripts") or {}
    steps = []
    for name in list(scripts.keys())[:5]:
        steps.append({"command": name, "source": f"pyproject.toml project.scripts.{name}"})
    poetry_scripts = ((data.get("tool") or {}).get("poetry") or {}).get("scripts") or {}
    for name in list(poetry_scripts.keys())[:5]:
        steps.append({"command": f"poetry run {name}", "source": f"pyproject.toml tool.poetry.scripts.{name}"})
    return steps


def _framework_run_steps(repo_path: Path, frameworks: set[str], architecture: dict[str, Any]) -> list[dict[str, str]]:
    steps = []
    if "Streamlit" in frameworks:
        streamlit_entry = _find_streamlit_entry(repo_path) or "app.py"
        steps.append({"command": f"streamlit run {streamlit_entry}", "source": "Streamlit dependency/import"})
    if "Flask" in frameworks:
        flask_entry = _find_existing(repo_path, ["app.py", "wsgi.py", "main.py"])
        command = "flask run" if not flask_entry else f"python {flask_entry}"
        steps.append({"command": command, "source": "Flask dependency/import"})
    if "FastAPI" in frameworks:
        module = _fastapi_module(repo_path) or "main:app"
        steps.append({"command": f"uvicorn {module} --reload", "source": "FastAPI dependency/import"})
    if (repo_path / "manage.py").exists():
        steps.append({"command": "python manage.py runserver", "source": "manage.py"})
    if not steps:
        for entry in architecture.get("entry_points") or _guess_entry_points(repo_path):
            if entry.endswith(".py"):
                steps.append({"command": f"python {entry}", "source": "入口文件候选"})
                break
    return steps


def _docker_steps(repo_path: Path, tools: set[str]) -> list[dict[str, str]]:
    if "Docker Compose" in tools or (repo_path / "docker-compose.yml").exists() or (repo_path / "docker-compose.yaml").exists():
        return [{"command": "docker compose up --build", "source": "docker-compose.yml"}]
    if "Docker" in tools or (repo_path / "Dockerfile").exists():
        return [{"command": "docker build -t repo-app . && docker run --rm -p 8000:8000 repo-app", "source": "Dockerfile"}]
    return []


def _find_env_vars(repo_path: Path) -> list[str]:
    patterns = [
        re.compile(r"(?:os\.getenv|os\.environ\.get|os\.environ\[)\(['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?"),
        re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"process\.env\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]"),
    ]
    env_vars = set()
    for path in _iter_text_files(repo_path):
        if path.suffix.lower() not in {".py", ".js", ".ts", ".jsx", ".tsx"}:
            continue
        text = _read_text(path)
        for pattern in patterns:
            for match in pattern.finditer(text):
                env_vars.add(match.group(1))
    return sorted(env_vars)


def _readme_run_notes(repo_path: Path) -> list[str]:
    notes = []
    for path in _readme_paths(repo_path):
        for raw_line in _read_text(path).splitlines():
            original = raw_line.strip()
            clean = original.strip("#").strip()
            if not clean:
                continue
            if re.match(r"^#{1,4}\s+.*(安装|运行|启动|usage|quickstart|installation|run|start)", original, re.IGNORECASE):
                notes.append(f"{path.name}: {clean[:180]}")
                continue
            for inline_command in re.findall(r"`([^`]+)`", original):
                inline_command = inline_command.strip()
                if _looks_like_run_command(inline_command):
                    notes.append(f"{path.name}: {inline_command}")
            line_command = original.lstrip("$> ").strip()
            if _looks_like_run_command(line_command):
                notes.append(f"{path.name}: {line_command}")
    return notes


def _extract_shell_commands(text: str) -> list[str]:
    commands = []
    in_fence = False
    fence_lang = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            fence_lang = line.strip("`").strip().lower()
            continue
        clean = line.lstrip("$> ").strip()
        if not clean:
            continue
        inline_commands = re.findall(r"`([^`]+)`", clean)
        for inline_command in inline_commands:
            inline_command = inline_command.strip()
            if _looks_like_run_command(inline_command):
                commands.append(inline_command)
        if in_fence and (not fence_lang or fence_lang in {"bash", "sh", "shell", "console", "powershell", "cmd", "text"}):
            if _looks_like_run_command(clean):
                commands.append(clean)
        elif _looks_like_run_command(clean):
            commands.append(clean)
    return commands


def _looks_like_run_command(command: str) -> bool:
    if len(command) > 180:
        return False
    return bool(COMMAND_PREFIX_RE.search(command.strip()))


def _script_files(repo_path: Path) -> list[str]:
    scripts_dir = repo_path / "scripts"
    if not scripts_dir.exists():
        return []
    scripts = []
    for path in scripts_dir.iterdir():
        if path.is_file() and path.suffix.lower() in {".py", ".ps1", ".sh", ".bat", ".cmd"}:
            scripts.append(path.relative_to(repo_path).as_posix())
    return sorted(scripts)


def _find_streamlit_entry(repo_path: Path) -> str | None:
    candidates = ["app.py", "streamlit_app.py", "Home.py", "main.py"]
    found = _find_existing(repo_path, candidates)
    if found:
        return found
    for path in _iter_text_files(repo_path):
        if path.suffix.lower() == ".py" and "import streamlit" in _read_text(path):
            return path.relative_to(repo_path).as_posix()
    return None


def _fastapi_module(repo_path: Path) -> str | None:
    for path in _iter_text_files(repo_path):
        if path.suffix.lower() != ".py":
            continue
        text = _read_text(path)
        if "FastAPI(" in text:
            module = path.relative_to(repo_path).with_suffix("").as_posix().replace("/", ".")
            return f"{module}:app"
    return None


def _guess_entry_points(repo_path: Path) -> list[str]:
    candidates = [
        "app.py",
        "main.py",
        "manage.py",
        "wsgi.py",
        "asgi.py",
        "server.py",
        "streamlit_app.py",
        "index.js",
        "src/main.ts",
        "src/main.tsx",
        "src/App.jsx",
        "src/App.tsx",
    ]
    return [candidate for candidate in candidates if (repo_path / candidate).exists()]


def _find_existing(repo_path: Path, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if (repo_path / candidate).exists():
            return candidate
    return None


def _readme_paths(repo_path: Path) -> list[Path]:
    paths = []
    for name in ("README.md", "README.rst", "README.txt", "readme.md"):
        path = repo_path / name
        if path.exists():
            paths.append(path)
    return paths


def _dedupe_steps(steps: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped = []
    seen = set()
    for item in steps:
        command = " ".join((item.get("command") or "").split())
        if not command or command in seen:
            continue
        seen.add(command)
        deduped.append({"command": command, "source": item.get("source", "")})
    return deduped


def _is_run_question(question: str) -> bool:
    lower = question.lower()
    return any(
        word in lower
        for word in [
            "本地跑",
            "怎么运行",
            "run locally",
            "how do i run",
            "locally",
            "启动",
            "install",
            "安装",
            "运行",
            "start",
        ]
    )


def _is_overview_question(question: str) -> bool:
    lower = question.lower()
    return any(
        word in lower
        for word in [
            "干什么",
            "做什么",
            "项目用途",
            "仓库用途",
            "是什么项目",
            "what is this",
            "what does",
            "purpose",
            "overview",
        ]
    )


def _run_chunk_bonus(rel_path: str, content: str) -> int:
    lower_path = rel_path.lower()
    score = 0
    if "readme" in lower_path or lower_path in {"package.json", "pyproject.toml", "requirements.txt", "dockerfile"}:
        score += 6
    if COMMAND_HINT_RE.search(content):
        score += 8
    if any(keyword in content.lower() for keyword in RUN_KEYWORDS):
        score += 3
    return score


def _template_qa_answer(question: str, chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "没有在仓库文本中检索到足够相关的片段，建议换一个更具体的问题。"
    lines = [f"针对问题“{question}”，我检索到了这些相关片段。由于未使用 LLM，下面是基于片段的简要回答："]
    for chunk in chunks[:4]:
        preview = " ".join(chunk["content"].split())[:220]
        lines.append(f"- {chunk['path']}:{chunk['start_line']}：{preview}")
    return "\n".join(lines)


def _build_qa_prompt(question: str, analysis: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"[{item['path']}:{item['start_line']}-{item['end_line']}]\n{item['content']}"
        for item in chunks
    )
    summary = {
        "repo": analysis.get("repo_info", {}),
        "tech_stack": analysis.get("tech_stack", {}),
        "architecture": analysis.get("architecture", {}),
    }
    return f"""
你是仓库代码问答助手。只能根据给定的仓库摘要和检索片段回答，不要编造未出现的文件或函数。

仓库摘要：
{summary}

检索片段：
{context}

用户问题：{question}

请用中文回答，并在涉及具体信息时标注来源文件。
""".strip()


def _iter_text_files(repo_path: Path):
    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        for filename in filenames:
            path = Path(current_root) / filename
            if path.suffix.lower() in TEXT_EXTENSIONS or path.name.lower() in {"readme", "dockerfile", "makefile"}:
                yield path


def _chunk_text(text: str, rel_path: str, max_lines: int = 80) -> list[dict[str, Any]]:
    lines = text.splitlines()
    chunks = []
    for start in range(0, len(lines), max_lines):
        block = "\n".join(lines[start : start + max_lines]).strip()
        if not block:
            continue
        chunks.append(
            {
                "path": rel_path,
                "start_line": start + 1,
                "end_line": min(len(lines), start + max_lines),
                "content": block[:5000],
            }
        )
    return chunks


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text)
        if token.lower() not in {"the", "and", "for", "with", "this", "that", "怎么", "哪些", "项目"}
    }


def _source_rows(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": item["path"],
            "line_range": f"{item['start_line']}-{item['end_line']}",
            "score": item.get("score", 0),
        }
        for item in chunks
    ]


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 1_500_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
