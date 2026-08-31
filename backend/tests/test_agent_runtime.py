from __future__ import annotations

import pytest

from ai_workbench_common.agent_runtime import AgentRuntime, RetryableError
from ai_workbench_common.agentic import AgentContext, AgentState, BaseAgent
from common.models import Alert, AlertSeverity


class FlakyAgent(BaseAgent):
    name = "flaky-agent"

    def __init__(self) -> None:
        self.calls = 0

    async def initialize(self, context: AgentContext, state: AgentState) -> None:
        state.execution_status = "initialized"

    async def plan(self, context: AgentContext, state: AgentState) -> dict[str, str]:
        return {"phase": "unit-test"}

    async def execute(self, context: AgentContext) -> dict[str, str]:
        self.calls += 1
        if self.calls == 1:
            raise RetryableError("temporary tool failure")
        return {"status": "ok"}

    async def validate(self, result: object) -> bool:
        return isinstance(result, dict) and result.get("status") == "ok"


@pytest.mark.asyncio
async def test_agent_runtime_retries_and_reflects() -> None:
    runtime = AgentRuntime(max_attempts=2)
    agent = FlakyAgent()
    context = AgentContext(
        alert=Alert(
            source="prometheus",
            name="Latency",
            service="payments",
            severity=AlertSeverity.HIGH,
            description="latency spike",
        )
    )

    outcome = await runtime.run(agent, context)

    assert outcome.result == {"status": "ok"}
    assert outcome.state.execution_status == "succeeded"
    assert outcome.state.retries == 1
    assert context.previous_agent_results.get("flaky-agent:reflection")
