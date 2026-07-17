from __future__ import annotations

import hashlib
import math
from collections import Counter

import httpx
from langchain_core.embeddings import Embeddings

from common.config import Settings
from common.logging import get_logger

logger = get_logger(__name__)


class HashingEmbeddingModel(Embeddings):
    """Small deterministic embedding model for local correlation and tests."""

    def __init__(self, dimensions: int = 128) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = [token.strip().lower() for token in text.replace("/", " ").split() if token.strip()]
        counts = Counter(tokens)
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1 if digest[4] % 2 == 0 else -1
            vector[index] += sign * float(count)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)


class AzureOpenAIEmbeddingModel(Embeddings):
    """Semantic embeddings via Azure OpenAI with resilient local fallback."""

    def __init__(self, settings: Settings) -> None:
        self._endpoint = str(getattr(settings, "azure_openai_endpoint", "") or "").strip().rstrip("/")
        self._api_key = str(getattr(settings, "azure_openai_api_key", "") or "").strip()
        self._deployment = str(getattr(settings, "azure_openai_embeddings_deployment", "") or "").strip()
        self._api_version = str(getattr(settings, "azure_openai_api_version", "2024-06-01") or "2024-06-01").strip()
        self._timeout_seconds = float(getattr(settings, "azure_openai_embeddings_timeout_seconds", 8.0) or 8.0)
        self._fallback = HashingEmbeddingModel()

    def _embeddings_endpoint(self) -> str:
        return (
            f"{self._endpoint}/openai/deployments/{self._deployment}/embeddings"
            f"?api-version={self._api_version}"
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._endpoint or not self._api_key or not self._deployment:
            logger.warning("azure openai embeddings unavailable: missing endpoint/key/deployment; using local fallback")
            return self._fallback.embed_documents(texts)

        payload = {"input": texts}
        headers = {"api-key": self._api_key, "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._embeddings_endpoint(), headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
        except Exception as exc:
            logger.warning("azure openai embeddings call failed; using local fallback", extra={"error": str(exc)})
            return self._fallback.embed_documents(texts)

        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            logger.warning("azure openai embeddings returned unexpected shape; using local fallback")
            return self._fallback.embed_documents(texts)

        vectors: list[list[float]] = []
        for item in data:
            values = (item or {}).get("embedding") if isinstance(item, dict) else None
            if not isinstance(values, list):
                logger.warning("azure openai embeddings item missing values; using local fallback for this item")
                vectors.append(self._fallback.embed(texts[len(vectors)]))
                continue
            vectors.append([float(v) for v in values])
        return vectors


class VertexAIEmbeddingModel(AzureOpenAIEmbeddingModel):
    """Compatibility alias retained for existing imports."""


def get_embedding_model(settings: Settings) -> Embeddings:
    """Select embedding backend with Azure OpenAI preferred for cloud deployment."""
    if bool(getattr(settings, "azure_openai_embeddings_enabled", False)):
        return AzureOpenAIEmbeddingModel(settings)
    return HashingEmbeddingModel()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
