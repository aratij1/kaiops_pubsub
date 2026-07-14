from common.config import Settings
from common.embeddings import HashingEmbeddingModel, VertexAIEmbeddingModel, get_embedding_model
from common.model_evaluation import VertexEvaluationClient


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_get_embedding_model_defaults_to_hashing() -> None:
    model = get_embedding_model(_settings())
    assert isinstance(model, HashingEmbeddingModel)


def test_get_embedding_model_returns_vertex_when_enabled() -> None:
    model = get_embedding_model(_settings(VERTEX_AI_EMBEDDINGS_ENABLED=True, GCP_PROJECT_ID="kaiops-prod"))
    assert isinstance(model, VertexAIEmbeddingModel)


def test_vertex_embedding_model_falls_back_without_project_id() -> None:
    model = VertexAIEmbeddingModel(_settings(VERTEX_AI_EMBEDDINGS_ENABLED=True, GCP_PROJECT_ID=""))
    vectors = model.embed_documents(["payment latency alert"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 128  # falls back to HashingEmbeddingModel's default dimensions


def test_vertex_embedding_model_falls_back_on_missing_credentials(monkeypatch) -> None:
    model = VertexAIEmbeddingModel(_settings(VERTEX_AI_EMBEDDINGS_ENABLED=True, GCP_PROJECT_ID="kaiops-prod"))
    monkeypatch.setattr("common.embeddings.get_google_bearer_token", lambda **kwargs: None)

    vectors = model.embed_documents(["payment latency alert"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 128


def test_vertex_embedding_model_parses_real_predict_response(monkeypatch) -> None:
    model = VertexAIEmbeddingModel(_settings(VERTEX_AI_EMBEDDINGS_ENABLED=True, GCP_PROJECT_ID="kaiops-prod"))
    monkeypatch.setattr("common.embeddings.get_google_bearer_token", lambda **kwargs: "fake-token")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"predictions": [{"embeddings": {"values": [0.1, 0.2, 0.3], "statistics": {"token_count": 4, "truncated": False}}}]}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            assert json["instances"] == [{"content": "hello", "task_type": "RETRIEVAL_DOCUMENT"}]
            return _FakeResponse()

    import common.embeddings as embeddings_module

    original_client = embeddings_module.httpx.Client
    embeddings_module.httpx.Client = _FakeClient
    try:
        vectors = model.embed_documents(["hello"])
    finally:
        embeddings_module.httpx.Client = original_client

    assert vectors == [[0.1, 0.2, 0.3]]


def test_vertex_evaluation_client_disabled_by_default() -> None:
    client = VertexEvaluationClient(_settings())
    assert client.enabled is False
    assert client.evaluate("some model output") is None


def test_vertex_evaluation_client_requires_project_id() -> None:
    client = VertexEvaluationClient(_settings(VERTEX_EVALUATION_ENABLED=True, GCP_PROJECT_ID=""))
    assert client.enabled is False


def test_vertex_evaluation_client_rejects_unsupported_metric() -> None:
    client = VertexEvaluationClient(_settings(VERTEX_EVALUATION_ENABLED=True, GCP_PROJECT_ID="kaiops-prod"))
    assert client.evaluate("text", metric="not-a-real-metric") is None


def test_vertex_evaluation_client_requires_context_for_groundedness() -> None:
    client = VertexEvaluationClient(_settings(VERTEX_EVALUATION_ENABLED=True, GCP_PROJECT_ID="kaiops-prod"))
    assert client.evaluate("text", metric="groundedness", context=None) is None


def test_vertex_evaluation_client_parses_coherence_result(monkeypatch) -> None:
    client = VertexEvaluationClient(_settings(VERTEX_EVALUATION_ENABLED=True, GCP_PROJECT_ID="kaiops-prod"))
    monkeypatch.setattr("common.model_evaluation.get_google_bearer_token", lambda **kwargs: "fake-token")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"coherenceResult": {"score": 4.2, "explanation": "well structured", "confidence": 0.8}}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            assert json == {"coherenceInput": {"metricSpec": {}, "instance": {"prediction": "root cause is X"}}}
            return _FakeResponse()

    import common.model_evaluation as evaluation_module

    original_client = evaluation_module.httpx.Client
    evaluation_module.httpx.Client = _FakeClient
    try:
        result = client.evaluate("root cause is X", metric="coherence")
    finally:
        evaluation_module.httpx.Client = original_client

    assert result is not None
    assert result.metric == "coherence"
    assert result.score == 4.2
    assert result.confidence == 0.8


def test_vertex_evaluation_client_returns_none_on_malformed_response(monkeypatch) -> None:
    client = VertexEvaluationClient(_settings(VERTEX_EVALUATION_ENABLED=True, GCP_PROJECT_ID="kaiops-prod"))
    monkeypatch.setattr("common.model_evaluation.get_google_bearer_token", lambda **kwargs: "fake-token")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"unexpected": "shape"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            return _FakeResponse()

    import common.model_evaluation as evaluation_module

    original_client = evaluation_module.httpx.Client
    evaluation_module.httpx.Client = _FakeClient
    try:
        result = client.evaluate("text", metric="coherence")
    finally:
        evaluation_module.httpx.Client = original_client

    assert result is None


def test_setup_tracing_gcp_export_disabled_by_default() -> None:
    from common.telemetry import _add_gcp_trace_exporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    # No project id configured -> should log and return without raising.
    _add_gcp_trace_exporter(provider, _settings())
