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
        self.provider = "local"
        self.model_name = "hashing-token-counter-v1"
        self.fallback = False

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
        self.provider = "azure-openai"
        self.model_name = self._deployment or "unconfigured-azure-openai-embedding-deployment"
        self.fallback = False
        self.fallback_active = False
        self.last_error = ""

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
        if self.fallback_active:
            return self._fallback.embed_documents(texts)
        if not self._endpoint or not self._api_key or not self._deployment:
            logger.warning("azure openai embeddings unavailable: missing endpoint/key/deployment; using local fallback")
            self.fallback_active = True
            self.last_error = "missing endpoint/key/deployment"
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
            self.fallback_active = True
            self.last_error = str(exc)
            return self._fallback.embed_documents(texts)

        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            logger.warning("azure openai embeddings returned unexpected shape; using local fallback")
            self.fallback_active = True
            self.last_error = "unexpected response shape"
            return self._fallback.embed_documents(texts)

        vectors: list[list[float]] = []
        for item in data:
            values = (item or {}).get("embedding") if isinstance(item, dict) else None
            if not isinstance(values, list):
                logger.warning("azure openai embeddings item missing values; using local fallback for this item")
                self.last_error = "embedding item missing values"
                vectors.append(self._fallback.embed(texts[len(vectors)]))
                continue
            vectors.append([float(v) for v in values])
        return vectors


class OpenAIEmbeddingModel(Embeddings):
    """Semantic embeddings via OpenAI with resilient local fallback."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = str(getattr(settings, "openai_api_key", "") or "").strip()
        self._base_url = str(getattr(settings, "openai_base_url", "https://api.openai.com/v1") or "").strip().rstrip("/")
        self._model = str(getattr(settings, "openai_embedding_model", "text-embedding-3-large") or "text-embedding-3-large").strip()
        self._timeout_seconds = float(getattr(settings, "openai_embeddings_timeout_seconds", 15.0) or 15.0)
        self._fallback = HashingEmbeddingModel()
        self.provider = "openai"
        self.model_name = self._model
        self.dimensions = 3072 if self._model == "text-embedding-3-large" else None
        self.fallback = False
        self.fallback_active = False
        self.last_error = ""

    def _embeddings_endpoint(self) -> str:
        return f"{self._base_url}/embeddings"

    def embed(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.fallback_active:
            return self._fallback.embed_documents(texts)
        if not self._api_key or not self._base_url or not self._model:
            logger.warning("openai embeddings unavailable: missing api key/base url/model; using local fallback")
            self.fallback_active = True
            self.last_error = "missing api key/base url/model"
            return self._fallback.embed_documents(texts)

        payload = {"model": self._model, "input": texts}
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._embeddings_endpoint(), headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
        except Exception as exc:
            logger.warning("openai embeddings call failed; using local fallback", extra={"error": str(exc)})
            self.fallback_active = True
            self.last_error = str(exc)
            return self._fallback.embed_documents(texts)

        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            logger.warning("openai embeddings returned unexpected shape; using local fallback")
            self.fallback_active = True
            self.last_error = "unexpected response shape"
            return self._fallback.embed_documents(texts)

        vectors: list[list[float]] = []
        for item in sorted(data, key=lambda row: int(row.get("index", 0)) if isinstance(row, dict) else 0):
            values = (item or {}).get("embedding") if isinstance(item, dict) else None
            if not isinstance(values, list):
                logger.warning("openai embeddings item missing values; using local fallback for this item")
                self.last_error = "embedding item missing values"
                vectors.append(self._fallback.embed(texts[len(vectors)]))
                continue
            vectors.append([float(v) for v in values])
        return vectors


class VertexAIEmbeddingModel(AzureOpenAIEmbeddingModel):
    """Compatibility alias retained for existing imports."""


def describe_embedding_model(model: Embeddings) -> dict[str, object]:
    provider = str(getattr(model, "provider", "") or "").strip()
    model_name = str(getattr(model, "model_name", "") or "").strip()
    dimensions = getattr(model, "dimensions", None)
    if isinstance(model, HashingEmbeddingModel):
        provider = provider or "local"
        model_name = model_name or "hashing-token-counter-v1"
        dimensions = model.dimensions
    elif isinstance(model, AzureOpenAIEmbeddingModel):
        provider = provider or "azure-openai"
        model_name = model_name or model._deployment or "unconfigured-azure-openai-embedding-deployment"
    elif isinstance(model, OpenAIEmbeddingModel):
        provider = provider or "openai"
        model_name = model_name or model._model or "text-embedding-3-large"
        dimensions = dimensions or model.dimensions
    else:
        provider = provider or model.__class__.__name__
        model_name = model_name or model.__class__.__name__
    return {
        "provider": provider,
        "model": model_name,
        "dimensions": dimensions,
        "fallback_supported": isinstance(model, (AzureOpenAIEmbeddingModel, OpenAIEmbeddingModel)),
        "fallback_model": "hashing-token-counter-v1" if isinstance(model, (AzureOpenAIEmbeddingModel, OpenAIEmbeddingModel)) else None,
        "fallback_active": bool(getattr(model, "fallback_active", False)),
        "last_error": str(getattr(model, "last_error", "") or ""),
    }


def get_embedding_model(settings: Settings) -> Embeddings:
    """Select the configured enterprise embedding backend with deterministic fallback."""
    provider = str(getattr(settings, "rag_embedding_provider", "auto") or "auto").strip().lower()
    if provider == "azure-openai" or (provider == "auto" and bool(getattr(settings, "azure_openai_embeddings_enabled", False))):
        return AzureOpenAIEmbeddingModel(settings)
    if provider == "openai" or (provider == "auto" and bool(getattr(settings, "openai_api_key", None))):
        return OpenAIEmbeddingModel(settings)
    return HashingEmbeddingModel()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
