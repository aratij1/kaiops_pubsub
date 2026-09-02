from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from common.logging import get_logger
from common.telemetry import AGENT_EXECUTIONS, AGENT_STAGE_LATENCY
from opentelemetry import trace

from ai_workbench_common.agentic import AgentContext, AgentState, BaseAgent

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class RetryableError(RuntimeError):
    pass


class ValidationError(RuntimeError):
    pass


class PolicyViolation(RuntimeError):
    pass


class ToolFailure(RuntimeError):
    pass


class ExecutionFailure(RuntimeError):
    pass


class ContextFailure(RuntimeError):
    pass


@dataclass(slots=True)
class RuntimeResult:
    result: Any
    state: AgentState
    reflection: dict[str, Any]


@dataclass(slots=True)
class AgentRuntime:
    max_attempts: int = 2

    @staticmethod
    async def _timed_stage(
        agent_name: str,
        stage: str,
        func: Any,
        *,
        state: AgentState,
    ) -> Any:
        started = perf_counter()
        with tracer.start_as_current_span(f"agent.{agent_name}.{stage}") as span:
            span.set_attribute("kaiops.agent", agent_name)
            span.set_attribute("kaiops.stage", stage)
            span.set_attribute("kaiops.incident_id", state.incident_id or "")
            span.set_attribute("kaiops.alert_id", state.alert_id or "")
            span.set_attribute("kaiops.flow_id", state.flow_id or "")
            span.set_attribute("kaiops.trace_id", state.trace_id or "")
            span.set_attribute("kaiops.correlation_id", state.correlation_id or "")
            result = await func()
        AGENT_STAGE_LATENCY.labels(agent=agent_name, stage=stage).observe(max(0.0, perf_counter() - started))
        return result

    async def run(self, agent: BaseAgent, context: AgentContext) -> RuntimeResult:
        state = AgentState.from_context(context)
        state.execution_status = "initializing"
        state.apply(context)
        await self._timed_stage(agent.name, "initialize", lambda: agent.initialize(context, state), state=state)

        plan = await self._timed_stage(agent.name, "plan", lambda: agent.plan(context, state), state=state)
        if isinstance(plan, dict) and plan:
            state.decisions.append({"type": "plan", "value": plan})

        result: Any | None = None
        failure: Exception | None = None
        state.execution_status = "executing"

        for attempt in range(1, self.max_attempts + 1):
            try:
                state.retries = attempt - 1
                result = await self._timed_stage(agent.name, "execute", lambda: agent.execute(context), state=state)
                is_valid = await self._timed_stage(
                    agent.name,
                    "validate",
                    lambda current_result=result: agent.validate(current_result),
                    state=state,
                )
                if not is_valid:
                    raise ValidationError(f"{agent.name} returned invalid output")
                state.execution_status = "succeeded"
                await self._timed_stage(
                    agent.name,
                    "publish",
                    lambda current_result=result: agent.publish(context, state, current_result),
                    state=state,
                )
                failure = None
                break
            except RetryableError as exc:
                failure = exc
                state.observations.append(
                    {
                        "attempt": attempt,
                        "status": "retryable_error",
                        "error": str(exc),
                    }
                )
                if attempt >= self.max_attempts:
                    state.execution_status = "failed"
                    AGENT_EXECUTIONS.labels(agent=agent.name, status="failed").inc()
                    raise
            except Exception as exc:  # noqa: BLE001
                failure = exc
                state.execution_status = "failed"
                state.observations.append(
                    {
                        "attempt": attempt,
                        "status": "execution_error",
                        "error": str(exc),
                    }
                )
                AGENT_EXECUTIONS.labels(agent=agent.name, status="failed").inc()
                raise

        reflection = await self._timed_stage(
            agent.name,
            "reflect",
            lambda: agent.reflect(context, state, result=result, error=failure),
            state=state,
        )
        context.set_result(f"{agent.name}:reflection", reflection)
        state.apply(context)
        await self._timed_stage(agent.name, "shutdown", lambda: agent.shutdown(context, state), state=state)
        AGENT_EXECUTIONS.labels(agent=agent.name, status=state.execution_status).inc()
        logger.info(
            "agent runtime execution complete",
            extra={
                "agent": agent.name,
                "trace_id": state.trace_id or "",
                "flow_id": state.flow_id or "",
                "incident_id": state.incident_id or "",
                "retry_count": state.retries,
                "status": state.execution_status,
            },
        )
        return RuntimeResult(result=result, state=state, reflection=reflection)
