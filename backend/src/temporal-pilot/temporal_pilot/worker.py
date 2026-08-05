from __future__ import annotations

import asyncio

from common.config import get_settings
from temporalio.client import Client
from temporalio.worker import Worker
from temporal_pilot.activities import collect_context, execute_remediation_decision, request_compensation, resolve_recommendation
from temporal_pilot.workflow import KaiOpsIncidentPilotWorkflow


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[KaiOpsIncidentPilotWorkflow],
        activities=[collect_context, resolve_recommendation, execute_remediation_decision, request_compensation],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
