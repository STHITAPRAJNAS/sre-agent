from __future__ import annotations

from opensearchpy import AsyncOpenSearch

from sre_agent.config import get_settings


def _client() -> AsyncOpenSearch:
    s = get_settings()
    return AsyncOpenSearch(
        hosts=[s.opensearch_url],
        http_auth=(s.opensearch_username, s.opensearch_password) if s.opensearch_username else None,
        use_ssl=s.opensearch_url.startswith("https"),
        verify_certs=False,
        ssl_show_warn=False,
    )


async def search_code_chunks(
    query: str,
    repo_filter: str | None = None,
    top_k: int = 10,
) -> dict:
    """Search the AST-chunked code index in OpenSearch for relevant code snippets.

    Uses multi-match against content, file path, and symbol names. The index
    contains code chunks from all platform repositories, each tagged with repo,
    file_path, start_line, end_line, language, and chunk_type (function/class/method).

    Args:
        query: Free-text or error-message-based search, e.g.
            'KafkaDeserializer NullPointerException' or 'checkpoint timeout handler'.
        repo_filter: Optional repository name to restrict results, e.g. 'platform-jobs'.
        top_k: Number of results to return (default 10).

    Returns:
        dict with 'hits' list of {repo, file_path, start_line, end_line,
        language, chunk_type, symbol_name, content, score}.
    """
    s = get_settings()
    must: list = [
        {
            "multi_match": {
                "query": query,
                "fields": ["content^2", "symbol_name^3", "file_path"],
                "type": "best_fields",
            }
        }
    ]
    if repo_filter:
        must.append({"term": {"repo": repo_filter}})

    body = {"query": {"bool": {"must": must}}, "size": top_k}

    async with _client() as client:
        resp = await client.search(index=s.opensearch_code_index, body=body)

    hits = [
        {
            "repo": h["_source"].get("repo"),
            "file_path": h["_source"].get("file_path"),
            "start_line": h["_source"].get("start_line"),
            "end_line": h["_source"].get("end_line"),
            "language": h["_source"].get("language"),
            "chunk_type": h["_source"].get("chunk_type"),
            "symbol_name": h["_source"].get("symbol_name"),
            "content": h["_source"].get("content"),
            "score": h["_score"],
        }
        for h in resp["hits"]["hits"]
    ]
    return {"hits": hits, "total": resp["hits"]["total"]["value"]}


async def find_symbol(
    symbol_name: str,
    symbol_type: str = "function",
    repo_filter: str | None = None,
) -> dict:
    """Find a specific class, function, or method by exact name in the code index.

    Args:
        symbol_name: Exact or partial name of the class/function/method.
        symbol_type: Type filter — 'class' | 'function' | 'method' | 'module'.
        repo_filter: Optional repository name filter.

    Returns:
        dict with 'symbols' list of {repo, file_path, start_line, end_line,
        chunk_type, symbol_name, content}.
    """
    s = get_settings()
    must: list = [
        {"match": {"symbol_name": {"query": symbol_name, "operator": "and"}}},
        {"term": {"chunk_type": symbol_type}},
    ]
    if repo_filter:
        must.append({"term": {"repo": repo_filter}})

    body = {"query": {"bool": {"must": must}}, "size": 20}

    async with _client() as client:
        resp = await client.search(index=s.opensearch_code_index, body=body)

    symbols = [
        {
            "repo": h["_source"].get("repo"),
            "file_path": h["_source"].get("file_path"),
            "start_line": h["_source"].get("start_line"),
            "end_line": h["_source"].get("end_line"),
            "chunk_type": h["_source"].get("chunk_type"),
            "symbol_name": h["_source"].get("symbol_name"),
            "content": h["_source"].get("content"),
        }
        for h in resp["hits"]["hits"]
    ]
    return {"symbols": symbols, "total": resp["hits"]["total"]["value"]}


async def get_file_chunks(file_path: str, repo: str) -> dict:
    """Retrieve all indexed code chunks for a specific file.

    Args:
        file_path: Relative file path, e.g. 'src/jobs/orders/deserializer.py'.
        repo: Repository name, e.g. 'platform-jobs'.

    Returns:
        dict with 'chunks' list sorted by start_line, each with
        {start_line, end_line, chunk_type, symbol_name, content}.
    """
    s = get_settings()
    body = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"file_path": file_path}},
                    {"term": {"repo": repo}},
                ]
            }
        },
        "sort": [{"start_line": "asc"}],
        "size": 200,
    }

    async with _client() as client:
        resp = await client.search(index=s.opensearch_code_index, body=body)

    chunks = [
        {
            "start_line": h["_source"].get("start_line"),
            "end_line": h["_source"].get("end_line"),
            "chunk_type": h["_source"].get("chunk_type"),
            "symbol_name": h["_source"].get("symbol_name"),
            "content": h["_source"].get("content"),
        }
        for h in resp["hits"]["hits"]
    ]
    return {"file_path": file_path, "repo": repo, "chunks": chunks}
