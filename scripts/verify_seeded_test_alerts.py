from __future__ import annotations

import asyncio
import json
from uuid import UUID
from sqlalchemy.ext.asyncio import create_async_engine
from common.config import get_settings
from common.database import (
    AlertRecord,
    IncidentRecord,
    IncidentProjectionRecord,
    IncidentInvestigationBindingRecord,
    AuditLogRecord,
    ContextSnapshotRecord,
    create_session_factory,
)
from common.repository import IncidentRepository
from sqlalchemy import select

TEST_ALERT_IDS = [
    UUID("d1111111-1111-4111-8111-111111111111"),
    UUID("d2222222-2222-4222-8222-111111111111"),
    UUID("d3333333-3333-4333-8333-111111111111"),
]

async def verify():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    out = {}
    async with session_factory() as session:
        repo = IncidentRepository(session)
        for aid in TEST_ALERT_IDS:
            import inspect
            sig = inspect.signature(repo.get_processed_result_by_alert_id)
            if "tenant_id" in sig.parameters:
                res = await repo.get_processed_result_by_alert_id(str(aid), tenant_id="default")
            else:
                res = await repo.get_processed_result_by_alert_id(str(aid))
            
            if res:
                rec = res.get("recommendation") or {}
                meta = rec.get("metadata") or {}
                iter_inv = meta.get("iterative_investigation") or {}
                conclusion = iter_inv.get("conclusion") or {}
                out[str(aid)] = {
                    "alert_id": str(aid),
                    "alert_name": (res.get("alert") or {}).get("name"),
                    "incident_id": (res.get("incident") or {}).get("id"),
                    "status": iter_inv.get("status"),
                    "conclusive": iter_inv.get("conclusive"),
                    "confidence": conclusion.get("confidence"),
                    "claim": conclusion.get("claim"),
                    "rca_status": meta.get("rca_status"),
                    "review_required": not iter_inv.get("conclusive") or (conclusion.get("confidence", 0) < 0.85),
                }
            else:
                out[str(aid)] = {"error": "None returned"}

    with open("/app/verification_result.json", "w") as f:
        json.dump(out, f, indent=2)
    print("=== RESULTS WRITTEN TO /app/verification_result.json ===")

if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(verify())
    except Exception as e:
        with open("/app/err.log", "w") as ef:
            traceback.print_exc(file=ef)
        print("EXCEPTION CAUGHT:", e)
