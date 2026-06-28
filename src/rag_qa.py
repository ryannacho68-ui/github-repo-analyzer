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

CODE_REVIEW_KEYWORDS = {
    "问题",
    "风险",
    "漏洞",
    "bug",
    "issue",
    "problem",
    "risk",
    "security",
    "vulnerability",
    "unsafe",
    "异常",
    "报错",
    "隐患",
    "优化",
    "改进",
    "代码审查",
    "review",
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
                        "message": _qa_message(chunks, "已基于检索片段调用 Ollama 回答。"),
                    }
            except Exception:
                pass

    return {
        "answer": _template_qa_answer(question, chunks),
        "sources": _source_rows(chunks),
        "mode": "retrieval-template",
        "message": _qa_message(chunks, "LLM 未启用或不可用，已返回基于检索片段的模板回答。"),
    }


def retrieve_relevant_chunks(question: str, repo_path: Path, top_k: int = 6) -> list[dict[str, Any]]:
    repo_path = Path(repo_path)
    hints = _query_hints(question, repo_path)
    chroma_chunks = _retrieve_chromadb_chunks(question, repo_path, top_k, hints)
    if chroma_chunks:
        return chroma_chunks
    return _retrieve_keyword_chunks(question, repo_path, top_k, hints)


def _retrieve_keyword_chunks(
    question: str,
    repo_path: Path,
    top_k: int = 6,
    hints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    hints = hints or _query_hints(question, repo_path)
    query_tokens = _tokenize(question)
    if hints.get("is_run_question"):
        query_tokens |= RUN_KEYWORDS
    if not query_tokens and not hints.get("paths") and not hints.get("symbols"):
        return []

    scored_chunks = []
    for path in _iter_text_files(repo_path):
        rel_path = path.relative_to(repo_path).as_posix()
        text = _read_text(path)
        if not text:
            continue
        for chunk in _chunk_text(text, rel_path):
            score = _chunk_query_score(chunk, query_tokens, hints)
            if score <= 0:
                continue
            chunk["score"] = score
            chunk["retriever"] = "keyword"
            scored_chunks.append(chunk)

    return sorted(scored_chunks, key=lambda item: item["score"], reverse=True)[:top_k]


def _retrieve_chromadb_chunks(
    question: str,
    repo_path: Path,
    top_k: int = 6,
    hints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
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
        hints = hints or _query_hints(question, repo_path)
        chunks = _collect_rag_chunks(repo_path)
        if not chunks:
            return []

        embedding_provider = _resolve_embedding_provider()
        CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        collection_name = _chroma_collection_name(repo_path)
        collection = _ensure_chroma_collection(client, collection_name, chunks, embedding_provider)

        result = collection.query(
            query_embeddings=[_embedding_vectors([_query_embedding_text(query, hints)], embedding_provider)[0]],
            n_results=min(max(top_k * 4, top_k), len(chunks)),
            include=["documents", "metadatas", "distances"],
        )
        query_tokens = _tokenize(question)
        if hints.get("is_run_question"):
            query_tokens |= RUN_KEYWORDS
        reranked = []
        for chunk in _chroma_query_to_chunks(result):
            chunk["score"] = round(float(chunk.get("score") or 0) + _chunk_query_score(chunk, query_tokens, hints), 4)
            reranked.append(chunk)
        return sorted(reranked, key=lambda item: item["score"], reverse=True)[:top_k]
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


def _ensure_chroma_collection(
    client: Any,
    collection_name: str,
    chunks: list[dict[str, Any]],
    embedding_provider: dict[str, str],
) -> Any:
    signature = _corpus_signature(chunks, embedding_provider)
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
    _index_chroma_chunks(collection, chunks, embedding_provider)
    _write_chroma_manifest(collection_name, {"signature": signature, "chunk_count": len(chunks)})
    return collection


def _index_chroma_chunks(collection: Any, chunks: list[dict[str, Any]], embedding_provider: dict[str, str]) -> None:
    for start in range(0, len(chunks), CHROMA_BATCH_SIZE):
        batch = chunks[start : start + CHROMA_BATCH_SIZE]
        embedding_texts = [_chunk_embedding_text(item) for item in batch]
        collection.add(
            ids=[item["id"] for item in batch],
            documents=[item["content"] for item in batch],
            metadatas=[
                {
                    "path": item["path"],
                    "start_line": int(item["start_line"]),
                    "end_line": int(item["end_line"]),
                    "chunk_type": item.get("chunk_type", "text"),
                    "symbol": item.get("symbol", ""),
                }
                for item in batch
            ],
            embeddings=_embedding_vectors(embedding_texts, embedding_provider),
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
                "chunk_type": str(metadata.get("chunk_type") or "text"),
                "symbol": str(metadata.get("symbol") or ""),
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


def _corpus_signature(chunks: list[dict[str, Any]], embedding_provider: dict[str, str] | None = None) -> str:
    digest = hashlib.sha1()
    provider = embedding_provider or {"kind": "hash", "model": ""}
    digest.update(json.dumps(provider, sort_keys=True).encode("utf-8", errors="ignore"))
    for chunk in chunks:
        digest.update(chunk["id"].encode("utf-8", errors="ignore"))
        digest.update(str(len(chunk["content"])).encode("ascii"))
        digest.update(hashlib.sha1(chunk["content"].encode("utf-8", errors="ignore")).digest())
    return digest.hexdigest()


def _chunk_id(chunk: dict[str, Any]) -> str:
    raw = f"{chunk['path']}:{chunk['start_line']}:{chunk['end_line']}:{chunk.get('chunk_type', '')}:{chunk.get('symbol', '')}"
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()
    return f"chunk_{digest}"


def _chunk_embedding_text(chunk: dict[str, Any]) -> str:
    label = " ".join(
        value
        for value in [
            chunk.get("path", ""),
            chunk.get("chunk_type", ""),
            chunk.get("symbol", ""),
        ]
        if value
    )
    return f"{label}\n{chunk.get('content', '')}"


def _query_embedding_text(query: str, hints: dict[str, Any]) -> str:
    extras = " ".join([*hints.get("paths", []), *hints.get("symbols", [])])
    return f"{extras}\n{query}".strip()


def _resolve_embedding_provider() -> dict[str, str]:
    model = os.environ.get("GITHUB_REPO_ANALYZER_EMBEDDING_MODEL", "").strip()
    if not model:
        return {"kind": "hash", "model": ""}
    if _ollama_embeddings(["embedding probe"], model):
        return {"kind": "ollama", "model": model}
    return {"kind": "hash", "model": ""}


def _embedding_vectors(texts: list[str], provider: dict[str, str]) -> list[list[float]]:
    if provider.get("kind") == "ollama" and provider.get("model"):
        vectors = _ollama_embeddings(texts, provider["model"])
        if not vectors or len(vectors) != len(texts):
            raise RuntimeError("Ollama embedding failed")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise RuntimeError("Ollama returned inconsistent embedding dimensions")
        return [_normalize_vector(vector) for vector in vectors]
    return [_hash_embedding(text) for text in texts]


def _ollama_embeddings(texts: list[str], model: str) -> list[list[float]] | None:
    if not texts:
        return []
    timeout = _embedding_timeout()
    endpoint = os.environ.get("GITHUB_REPO_ANALYZER_EMBEDDING_ENDPOINT", "").strip()
    endpoints = [endpoint] if endpoint else [_ollama_endpoint("/api/embed"), _ollama_endpoint("/api/embeddings")]

    for candidate in [item for item in endpoints if item]:
        try:
            if candidate.endswith("/api/embeddings"):
                vectors = []
                for text in texts:
                    response = requests.post(candidate, json={"model": model, "prompt": text}, timeout=timeout)
                    response.raise_for_status()
                    embedding = response.json().get("embedding")
                    if not isinstance(embedding, list):
                        raise RuntimeError("missing embedding")
                    vectors.append([float(value) for value in embedding])
                return vectors

            response = requests.post(candidate, json={"model": model, "input": texts}, timeout=timeout)
            response.raise_for_status()
            embeddings = response.json().get("embeddings")
            if isinstance(embeddings, list) and len(embeddings) == len(texts):
                return [[float(value) for value in vector] for vector in embeddings]
        except Exception:
            continue
    return None


def _ollama_endpoint(path: str) -> str:
    if DEFAULT_ENDPOINT.endswith("/api/generate"):
        return DEFAULT_ENDPOINT[: -len("/api/generate")] + path
    return "http://localhost:11434" + path


def _embedding_timeout() -> float:
    try:
        return max(float(os.environ.get("GITHUB_REPO_ANALYZER_EMBEDDING_TIMEOUT", "15")), 1.0)
    except ValueError:
        return 15.0


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


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


def _query_hints(question: str, repo_path: Path) -> dict[str, Any]:
    return {
        "paths": _extract_path_hints(question, repo_path),
        "symbols": _extract_symbol_hints(question),
        "is_run_question": _is_run_question(question),
        "is_code_review": _is_code_review_question(question),
    }


def _extract_path_hints(question: str, repo_path: Path) -> list[str]:
    normalized_question = (question or "").replace("\\", "/").lower()
    if not normalized_question:
        return []

    matches: list[str] = []
    for path in _iter_text_files(repo_path):
        rel_path = path.relative_to(repo_path).as_posix()
        lower_path = rel_path.lower()
        basename = path.name.lower()
        if lower_path in normalized_question or (
            "." in basename and len(basename) >= 5 and re.search(rf"(?<![\w./-]){re.escape(basename)}(?![\w./-])", normalized_question)
        ):
            matches.append(rel_path)

    return sorted(set(matches), key=lambda item: (item.count("/"), len(item), item.lower()))


def _extract_symbol_hints(question: str) -> list[str]:
    symbols: list[str] = []
    stopwords = {
        "class",
        "code",
        "def",
        "file",
        "function",
        "issue",
        "problem",
        "python",
        "return",
        "src",
        "test",
        "这个",
        "哪些",
        "怎么",
    }

    candidates: list[str] = []
    candidates.extend(re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", question or ""))
    candidates.extend(match.strip() for match in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", question or ""))
    candidates.extend(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", question or ""))

    for candidate in candidates:
        name = candidate.split(".")[-1].strip()
        if not name or name.lower() in stopwords:
            continue
        if "/" in name or "\\" in name or "." in name:
            continue
        if "_" not in name and name.islower() and len(name) < 5:
            continue
        if name not in symbols:
            symbols.append(name)
        if len(symbols) >= 12:
            break
    return symbols


def _chunk_query_score(chunk: dict[str, Any], query_tokens: set[str], hints: dict[str, Any]) -> float:
    rel_path = str(chunk.get("path") or "")
    lower_path = rel_path.lower()
    symbol = str(chunk.get("symbol") or "")
    lower_symbol = symbol.lower()
    chunk_type = str(chunk.get("chunk_type") or "text")
    content = str(chunk.get("content") or "")
    searchable = f"{content} {rel_path} {symbol} {chunk_type}"

    chunk_tokens = _tokenize(searchable)
    overlap = query_tokens & chunk_tokens
    score = float(len(overlap) * 4)
    score += sum(1 for token in query_tokens if token in lower_path)

    path_hints = {str(item).lower() for item in hints.get("paths", [])}
    if lower_path in path_hints:
        score += 80
    elif any(Path(path_hint).name.lower() == Path(lower_path).name.lower() for path_hint in path_hints):
        score += 35

    symbol_hints = {str(item).lower() for item in hints.get("symbols", [])}
    for symbol_hint in symbol_hints:
        if symbol_hint and symbol_hint == lower_symbol:
            score += 70
        elif symbol_hint and (symbol_hint in lower_symbol or symbol_hint in content.lower()):
            score += 20

    if hints.get("is_run_question"):
        score += _run_chunk_bonus(rel_path, content)
    if hints.get("is_code_review") and chunk_type in {"class", "function", "method", "code"}:
        score += 10
        score += min(len(_code_issue_hints(content)), 4) * 3
    if any(token in lower_path for token in {"readme", "config", "model", "route", "database"}):
        score += 1
    return round(score, 4)


def _is_code_review_question(question: str) -> bool:
    lower = (question or "").lower()
    return any(keyword in lower for keyword in CODE_REVIEW_KEYWORDS)


def _code_issue_hints(content: str) -> list[str]:
    hints = []
    checks = [
        (r"\bexcept\s*:", "存在 bare except，可能吞掉异常细节"),
        (r"except\s+Exception\s*:", "捕获 Exception 范围较宽，需要确认是否会掩盖真实错误"),
        (r"\beval\s*\(", "使用 eval，存在代码执行风险"),
        (r"\bexec\s*\(", "使用 exec，存在代码执行风险"),
        (r"shell\s*=\s*True", "命令执行启用 shell=True，需要确认输入是否可信"),
        (r"SELECT\s+.*\+|execute\s*\([^)]*%", "疑似 SQL 字符串拼接，需要确认是否参数化"),
        (r"password\s*=\s*['\"]|secret\s*=\s*['\"]|api[_-]?key\s*=\s*['\"]", "疑似硬编码敏感配置"),
        (r"TODO|FIXME|XXX", "包含 TODO/FIXME，可能是未完成逻辑"),
        (r"requests\.(get|post|put|delete)\([^)]*$", "请求调用可能缺少 timeout，需要结合上下文确认"),
    ]
    for pattern, message in checks:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            hints.append(message)
    return hints


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
    if _is_code_review_question(question):
        return _template_code_review_answer(question, chunks)
    lines = [f"针对问题“{question}”，我检索到了这些相关片段。由于未使用 LLM，下面是基于片段的简要回答："]
    for chunk in chunks[:4]:
        preview = " ".join(chunk["content"].split())[:220]
        label = _chunk_label(chunk)
        lines.append(f"- {label}：{preview}")
    if any((chunk.get("chunk_type") or "text") != "text" for chunk in chunks):
        lines.append("")
        lines.append("这些来源已经按代码文件、函数或类切分；启用 Ollama 后可以进一步生成具体代码解释。")
    return "\n".join(lines)


def _template_code_review_answer(question: str, chunks: list[dict[str, Any]]) -> str:
    lines = [
        f"针对问题“{question}”，我先定位到以下相关代码片段。",
        "当前未使用 LLM，因此这里只给出基于规则的代码审查线索，最终问题仍建议结合运行和测试确认：",
    ]
    for index, chunk in enumerate(chunks[:5], start=1):
        label = _chunk_label(chunk)
        hints = _code_issue_hints(chunk.get("content", ""))
        lines.append(f"{index}. {label}")
        if hints:
            for hint in hints[:4]:
                lines.append(f"   - 关注点：{hint}")
        else:
            lines.append("   - 关注点：未触发明显规则风险，可进一步检查输入校验、异常处理、边界条件和测试覆盖。")
    lines.append("")
    lines.append("建议打开 Ollama 后再次提问，系统会把这些代码片段作为 context，让模型输出更完整的影响分析和修改建议。")
    return "\n".join(lines)


def _build_qa_prompt(question: str, analysis: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"[{_chunk_label(item)}]\n{item['content']}"
        for item in chunks
    )
    summary = {
        "repo": analysis.get("repo_info", {}),
        "tech_stack": analysis.get("tech_stack", {}),
        "architecture": analysis.get("architecture", {}),
    }
    review_instruction = ""
    if _is_code_review_question(question):
        review_instruction = """
如果用户在询问代码问题、bug、安全风险或优化建议，请按以下结构回答：
1. 结论：先说明是否发现明确问题、疑似问题或仅能给出关注点。
2. 证据：逐条引用文件、行号、函数或类名。
3. 潜在影响：说明可能造成的错误、误报、性能或安全影响。
4. 修改建议：给出可执行的改法，不能编造未出现在片段中的 API。
5. 验证方式：建议补充的测试或手工确认步骤。
""".strip()
    return f"""
你是仓库代码问答助手。只能根据给定的仓库摘要和检索片段回答，不要编造未出现的文件或函数。
检索片段可能来自 README、配置文件，也可能来自源码的函数、类或文件级 chunk。回答具体代码问题时必须引用文件和行号。

仓库摘要：
{summary}

检索片段：
{context}

用户问题：{question}

{review_instruction}

请用中文回答，并在涉及具体信息时标注来源文件。
""".strip()


def _chunk_label(chunk: dict[str, Any]) -> str:
    symbol = chunk.get("symbol")
    chunk_type = chunk.get("chunk_type") or "text"
    symbol_part = f" {chunk_type}:{symbol}" if symbol else f" {chunk_type}"
    return f"{chunk['path']}:{chunk['start_line']}-{chunk['end_line']}{symbol_part}"


def _qa_message(chunks: list[dict[str, Any]], base_message: str) -> str:
    if not chunks:
        return base_message
    code_chunks = sum(1 for chunk in chunks if (chunk.get("chunk_type") or "text") in {"class", "function", "method", "code"})
    if code_chunks:
        return f"{base_message} 已命中 {code_chunks} 个代码级 chunk，可用于具体文件、函数或代码问题分析。"
    return base_message


def _iter_text_files(repo_path: Path):
    for current_root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        for filename in filenames:
            path = Path(current_root) / filename
            if path.suffix.lower() in TEXT_EXTENSIONS or path.name.lower() in {"readme", "dockerfile", "makefile"}:
                yield path


def _chunk_text(text: str, rel_path: str, max_lines: int = 80) -> list[dict[str, Any]]:
    suffix = Path(rel_path).suffix.lower()
    if suffix == ".py":
        return _chunk_python_code(text, rel_path, max_lines=max_lines)
    if suffix in {".js", ".ts", ".jsx", ".tsx"}:
        return _chunk_braced_code(text, rel_path, max_lines=max_lines)
    return _line_chunks(text, rel_path, max_lines=max_lines, chunk_type="text")


def _chunk_python_code(text: str, rel_path: str, max_lines: int = 80) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _line_chunks(text, rel_path, max_lines=max_lines, chunk_type="code")

    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    covered_ranges: list[tuple[int, int]] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            chunks.append(_node_chunk(lines, rel_path, node, "class", node.name))
            covered_ranges.append((node.lineno, getattr(node, "end_lineno", node.lineno)))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    chunks.append(_node_chunk(lines, rel_path, item, "method", f"{node.name}.{item.name}"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.append(_node_chunk(lines, rel_path, node, "function", node.name))
            covered_ranges.append((node.lineno, getattr(node, "end_lineno", node.lineno)))

    chunks.extend(_uncovered_line_chunks(lines, rel_path, covered_ranges, max_lines=max_lines))
    return chunks or _line_chunks(text, rel_path, max_lines=max_lines, chunk_type="code")


def _node_chunk(lines: list[str], rel_path: str, node: ast.AST, chunk_type: str, symbol: str) -> dict[str, Any]:
    start_line = max(getattr(node, "lineno", 1), 1)
    end_line = max(getattr(node, "end_lineno", start_line), start_line)
    block = "\n".join(lines[start_line - 1 : end_line]).strip()
    return {
        "path": rel_path,
        "start_line": start_line,
        "end_line": end_line,
        "content": block[:5000],
        "chunk_type": chunk_type,
        "symbol": symbol,
    }


def _uncovered_line_chunks(
    lines: list[str],
    rel_path: str,
    covered_ranges: list[tuple[int, int]],
    max_lines: int = 80,
) -> list[dict[str, Any]]:
    if not lines:
        return []

    covered: set[int] = set()
    for start_line, end_line in covered_ranges:
        covered.update(range(start_line, end_line + 1))

    chunks: list[dict[str, Any]] = []
    current_start: int | None = None
    current_lines: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        if line_number in covered:
            if current_start is not None:
                chunks.extend(_range_line_chunks(current_lines, rel_path, current_start, max_lines=max_lines, chunk_type="code"))
            current_start = None
            current_lines = []
            continue
        if current_start is None:
            current_start = line_number
        current_lines.append(line)
    if current_start is not None:
        chunks.extend(_range_line_chunks(current_lines, rel_path, current_start, max_lines=max_lines, chunk_type="code"))
    return chunks


def _chunk_braced_code(text: str, rel_path: str, max_lines: int = 80) -> list[dict[str, Any]]:
    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    covered_ranges: list[tuple[int, int]] = []
    pattern = re.compile(
        r"\b(?:export\s+default\s+|export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
        r"|\b(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"
        r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
    )

    for match in pattern.finditer(text):
        symbol = next(group for group in match.groups() if group)
        start_line = text.count("\n", 0, match.start()) + 1
        end_line = _find_braced_end_line(text, match.end())
        if end_line <= start_line:
            end_line = min(len(lines), start_line + max_lines - 1)
        chunk_type = "class" if match.group(2) else "function"
        block = "\n".join(lines[start_line - 1 : end_line]).strip()
        if not block:
            continue
        chunks.append(
            {
                "path": rel_path,
                "start_line": start_line,
                "end_line": end_line,
                "content": block[:5000],
                "chunk_type": chunk_type,
                "symbol": symbol,
            }
        )
        covered_ranges.append((start_line, end_line))

    chunks.extend(_uncovered_line_chunks(lines, rel_path, covered_ranges, max_lines=max_lines))
    return chunks or _line_chunks(text, rel_path, max_lines=max_lines, chunk_type="code")


def _find_braced_end_line(text: str, search_from: int) -> int:
    open_index = text.find("{", search_from)
    if open_index < 0:
        return text.count("\n", 0, search_from) + 1

    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text.count("\n", 0, index) + 1
    return text.count("\n") + 1


def _line_chunks(text: str, rel_path: str, max_lines: int = 80, chunk_type: str = "text") -> list[dict[str, Any]]:
    lines = text.splitlines()
    return _range_line_chunks(lines, rel_path, 1, max_lines=max_lines, chunk_type=chunk_type)


def _range_line_chunks(
    lines: list[str],
    rel_path: str,
    first_line_number: int,
    max_lines: int = 80,
    chunk_type: str = "text",
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for start in range(0, len(lines), max_lines):
        block = "\n".join(lines[start : start + max_lines]).strip()
        if not block:
            continue
        start_line = first_line_number + start
        end_line = first_line_number + min(len(lines), start + max_lines) - 1
        chunks.append(
            {
                "path": rel_path,
                "start_line": start_line,
                "end_line": end_line,
                "content": block[:5000],
                "chunk_type": chunk_type,
                "symbol": "",
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
            "chunk_type": item.get("chunk_type", "text"),
            "symbol": item.get("symbol", ""),
            "retriever": item.get("retriever", ""),
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
