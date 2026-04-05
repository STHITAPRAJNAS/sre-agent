from __future__ import annotations

import litellm

from sre_agent.config import get_settings


async def embed(text: str) -> list[float]:
    """Generate a text embedding using the configured embedding model.

    Uses LiteLLM so the model is configurable via EMBEDDING_MODEL env var.
    Defaults to OpenAI text-embedding-3-small (1536 dims).

    Args:
        text: Text to embed. Will be truncated to 8191 tokens by the model.

    Returns:
        List of floats representing the embedding vector.
    """
    s = get_settings()
    # Truncate very long texts to avoid token limit errors
    text = text[:8000]

    resp = await litellm.aembedding(
        model=s.embedding_model,
        input=[text],
        api_key=s.openai_api_key if s.openai_api_key else None,
    )
    return resp.data[0]["embedding"]
