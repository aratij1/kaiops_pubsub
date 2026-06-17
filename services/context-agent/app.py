from __future__ import annotations

from common.config import get_settings
from common.models import Alert, Context, Incident
from common.service import create_app
from common.topics import CONTEXT_EVENTS
from context_agent import ContextIntelligenceAgent

settings = get_settings()
settings.service_name = "context-agent"
agent = ContextIntelligenceAgent()
app = create_app(title="KaiOps Context Intelligence Agent", settings=settings)


@app.post("/collect", response_model=Context)
async def collect(payload: dict) -> Context:
    alert = Alert.model_validate(payload["alert"])
    incident = Incident.model_validate(payload["incident"])
    context = await agent.collect(alert, incident)
    await app.state.producer.publish(CONTEXT_EVENTS, {"context": context, "incident": incident}, key=alert.service)
    return context
