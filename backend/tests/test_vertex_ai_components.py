from common.config import Settings
from common.embeddings import AzureOpenAIEmbeddingModel, HashingEmbeddingModel, VertexAIEmbeddingModel, get_embedding_model
from common.model_evaluation import VertexEvaluationClient


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_get_embedding_model_defaults_to_hashing() -> None:
    model = get_embedding_model(_settings())
    assert isinstance(model, HashingEmbeddingModel)


def test_get_embedding_model_returns_azure_when_enabled() -> None:
    model = get_embedding_model(
        _settings(
            AZURE_OPENAI_EMBEDDINGS_ENABLED=True,
            AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com",
            AZURE_OPENAI_API_KEY="key",
            AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT="text-embedding-3-large",
        )
    )
    assert isinstance(model, AzureOpenAIEmbeddingModel)


def test_azure_embedding_compat_alias_points_to_azure_implementation() -> None:
    model = VertexAIEmbeddingModel(
        _settings(
            AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com",
            AZURE_OPENAI_API_KEY="key",
            AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT="text-embedding-3-large",
        )
    )
    assert isinstance(model, AzureOpenAIEmbeddingModel)


def test_azure_embedding_model_falls_back_without_required_settings() -> None:
    model = AzureOpenAIEmbeddingModel(_settings())
    vectors = model.embed_documents(["payment latency alert"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 128


def test_azure_embedding_model_parses_response(monkeypatch) -> None:
    model = AzureOpenAIEmbeddingModel(
        _settings(
            AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com",
            AZURE_OPENAI_API_KEY="key",
            AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT="embed-deploy",
        )
    )

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            assert json == {"input": ["hello"]}
            return _FakeResponse()

    import common.embeddings as embeddings_module

    original_client = embeddings_module.httpx.Client
    embeddings_module.httpx.Client = _FakeClient
    try:
        vectors = model.embed_documents(["hello"])
    finally:
        embeddings_module.httpx.Client = original_client

    assert vectors == [[0.1, 0.2, 0.3]]


def test_azure_evaluation_client_disabled_by_default() -> None:
    client = VertexEvaluationClient(_settings())
    assert client.enabled is False
    assert client.evaluate("some model output") is None


def test_azure_evaluation_client_rejects_unsupported_metric() -> None:
    client = VertexEvaluationClient(_settings(AZURE_AI_EVALUATION_ENABLED=True))
    assert client.evaluate("text", metric="not-a-real-metric") is None


def test_azure_evaluation_client_requires_context_for_groundedness() -> None:
    client = VertexEvaluationClient(_settings(AZURE_AI_EVALUATION_ENABLED=True))
    assert client.evaluate("text", metric="groundedness", context=None) is None


def test_azure_evaluation_client_parses_json_result(monkeypatch) -> None:
    client = VertexEvaluationClient(
        _settings(
            AZURE_AI_EVALUATION_ENABLED=True,
            AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com",
            AZURE_OPENAI_API_KEY="key",
            AZURE_AI_EVALUATION_DEPLOYMENT="eval-deploy",
        )
    )

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"score": 0.82, "explanation": "well structured", "confidence": 0.8}'
                        }
                    }
                ]
            }

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
        result = client.evaluate("root cause is X", metric="coherence")
    finally:
        evaluation_module.httpx.Client = original_client

    assert result is not None
    assert result.metric == "coherence"
    assert result.score == 0.82
    assert result.confidence == 0.8


def test_setup_tracing_azure_export_disabled_by_default() -> None:
    from common.telemetry import _add_azure_monitor_exporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    _add_azure_monitor_exporter(provider, _settings())
