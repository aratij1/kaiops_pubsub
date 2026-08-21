from __future__ import annotations

import pytest

from test_approval_context import load_approval_app_module


@pytest.mark.asyncio
async def test_capacity_is_isolated_by_tenant(sqlite_session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_approval_app_module()
    module.app.state.session_factory = sqlite_session_factory
    monkeypatch.setattr(module, "ZoneInfo", lambda _value: object())

    for tenant_id, hours in (("tenant-a", 20), ("tenant-b", 35)):
        request = module.CapacityRequest(
            tenant_id=tenant_id,
            username="shared.reviewer",
            resource_names=["payments"],
            weekly_hours=hours,
        )
        await module.upsert_capacity("shared.reviewer", request)

    tenant_a = await module.list_capacity("tenant-a")
    tenant_b = await module.list_capacity("tenant-b")

    assert [row["weekly_hours"] for row in tenant_a["rows"]] == [20]
    assert [row["weekly_hours"] for row in tenant_b["rows"]] == [35]


@pytest.mark.asyncio
async def test_capacity_rejects_placeholder_tenant(sqlite_session_factory) -> None:
    module = load_approval_app_module()
    module.app.state.session_factory = sqlite_session_factory

    with pytest.raises(ValueError, match="verified tenant_id"):
        await module.list_capacity("default")
