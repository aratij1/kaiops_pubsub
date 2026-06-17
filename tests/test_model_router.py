import pytest
from common.models import AlertSeverity
from model_router import ModelRouter, ModelTask


def test_model_router_selection_rules() -> None:
    router = ModelRouter()

    assert router.select_model(severity=AlertSeverity.CRITICAL, task=ModelTask.RCA) == "gpt-5"
    assert router.select_model(severity=AlertSeverity.HIGH, task=ModelTask.RCA) == "claude"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.SUMMARIZATION) == "gemini"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL) == "local-llama"


@pytest.mark.asyncio
async def test_model_router_failover() -> None:
    router = ModelRouter()
    router.providers["gpt-5"].healthy = False

    response = await router.route(
        severity=AlertSeverity.CRITICAL,
        task=ModelTask.RCA,
        prompt="rca",
        payload={"summary": "payment latency"},
    )

    assert response["model"] == "gpt-4o"
