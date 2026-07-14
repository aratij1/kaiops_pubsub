from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings

from common.config import Settings
from common.gcp_auth import get_google_bearer_token
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


class VertexAIEmbeddingModel(Embeddings):
    """Real semantic embeddings via Vertex AI's text embeddings predict API.

    Falls back to a HashingEmbeddingModel instance on any failure (missing
    credentials, network error, malformed response) so callers never crash —
    they just silently get lower-quality vectors for that call, matching the
    fallback behavior used by GooglePubSubPublisher/SafetyAnalyzer elsewhere.
    """

    def __init__(self, settings: Settings) -> None:
        self._project_id = str(getattr(settings, "gcp_project_id", "") or "").strip()
        self._region = str(getattr(settings, "gcp_region", "us-central1") or "us-central1").strip() or "us-central1"
        self._model = str(getattr(settings, "vertex_ai_embeddings_model", "text-embedding-005") or "text-embedding-005").strip()
        self._task_type = str(getattr(settings, "vertex_ai_embeddings_task_type", "RETRIEVAL_DOCUMENT") or "RETRIEVAL_DOCUMENT").strip()
        self._output_dimensionality = int(getattr(settings, "vertex_ai_embeddings_output_dimensionality", 0) or 0)
        self._timeout_seconds = float(getattr(settings, "vertex_ai_embeddings_timeout_seconds", 8.0) or 8.0)
        self._fallback = HashingEmbeddingModel()

    def _endpoint(self) -> str:
        return (
            f"https://{self._region}-aiplatform.googleapis.com/v1/projects/{self._project_id}"
            f"/locations/{self._region}/publishers/google/models/{self._model}:predict"
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._project_id:
            logger.warning("vertex ai embeddings unavailable: missing GCP_PROJECT_ID; using local fallback")
            return self._fallback.embed_documents(texts)

        token = get_google_bearer_token()
        if not token:
            return self._fallback.embed_documents(texts)

        instances: list[dict[str, Any]] = [{"content": text, "task_type": self._task_type} for text in texts]
        parameters: dict[str, Any] = {}
        if self._output_dimensionality > 0:
            parameters["outputDimensionality"] = self._output_dimensionality

        payload: dict[str, Any] = {"instances": instances}
        if parameters:
            payload["parameters"] = parameters

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._endpoint(), headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
        except Exception as exc:
            logger.warning("vertex ai embeddings call failed; using local fallback", extra={"error": str(exc)})
            return self._fallback.embed_documents(texts)

        predictions = parsed.get("predictions") if isinstance(parsed, dict) else None
        if not isinstance(predictions, list) or len(predictions) != len(texts):
            logger.warning("vertex ai embeddings returned unexpected shape; using local fallback")
            return self._fallback.embed_documents(texts)

        vectors: list[list[float]] = []
        for prediction in predictions:
            embedding = (prediction or {}).get("embeddings") if isinstance(prediction, dict) else None
            values = (embedding or {}).get("values") if isinstance(embedding, dict) else None
            if not isinstance(values, list):
                logger.warning("vertex ai embeddings prediction missing values; using local fallback for this item")
                vectors.append(self._fallback.embed(texts[len(vectors)]))
                continue
            vectors.append([float(v) for v in values])
        return vectors


def get_embedding_model(settings: Settings) -> Embeddings:
    """Select the embedding backend. Defaults to the local hashing model unless
    VERTEX_AI_EMBEDDINGS_ENABLED=true is explicitly set."""
    if bool(getattr(settings, "vertex_ai_embeddings_enabled", False)):
        return VertexAIEmbeddingModel(settings)
    return HashingEmbeddingModel()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
