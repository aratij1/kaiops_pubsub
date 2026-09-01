from __future__ import annotations

import pytest

from connector_hub.contracts import ConnectorOperationUnavailable, ConnectionProfile
from connector_hub.registry import CONNECTOR_CATALOG, default_connector_registry
from connector_hub.secrets import EnvironmentSecretProvider, SecretProviderRegistry, SecretResolutionError


def test_initial_connector_catalog_is_dynamic_and_complete() -> None:
    registry = default_connector_registry()
    metadata = registry.list_metadata()
    assert len(metadata) == len(CONNECTOR_CATALOG) == 25
    assert {row.connector_id for row in metadata} >= {"prometheus", "kubernetes", "jenkins", "mysql", "kafka", "airflow"}
    assert registry.get("kubernetes").get_capabilities() == [
        "resources.discover", "health.read", "kubernetes.restart_workload"
    ]


@pytest.mark.asyncio
async def test_metadata_only_connector_fails_closed() -> None:
    connector = default_connector_registry().get("prometheus")
    profile = ConnectionProfile(
        tenant_id="tenant-a", project_id="project-a", connection_id="connection-a", connector_id="prometheus"
    )
    with pytest.raises(ConnectorOperationUnavailable, match="no certified runtime adapter"):
        await connector.test_connection(profile)


@pytest.mark.asyncio
async def test_environment_secret_provider_resolves_reference_without_exposing_catalog_value(monkeypatch) -> None:
    monkeypatch.setenv("KAIMS_TEST_CONNECTOR_TOKEN", "secret-value")
    providers = SecretProviderRegistry([EnvironmentSecretProvider()])
    assert providers.supported_schemes() == ["env"]
    assert await providers.resolve("env://KAIMS_TEST_CONNECTOR_TOKEN") == "secret-value"


@pytest.mark.asyncio
async def test_secret_registry_rejects_implicit_or_unconfigured_provider() -> None:
    providers = SecretProviderRegistry()
    with pytest.raises(SecretResolutionError, match="explicit provider scheme"):
        await providers.resolve("KAIMS_TOKEN")
    with pytest.raises(SecretResolutionError, match="not configured"):
        await providers.resolve("vault://secret/data/kaims")

