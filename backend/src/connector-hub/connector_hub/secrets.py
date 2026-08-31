from __future__ import annotations

import os
from typing import Any, Protocol
from urllib.parse import urlparse


class SecretProvider(Protocol):
    scheme: str
    async def resolve(self, secret_ref: str) -> str: ...


class SecretResolutionError(RuntimeError):
    pass


class EnvironmentSecretProvider:
    scheme = "env"

    async def resolve(self, secret_ref: str) -> str:
        parsed = urlparse(secret_ref)
        name = (parsed.netloc + parsed.path).strip("/")
        if not name:
            raise SecretResolutionError("environment secret reference has no variable name")
        value = os.getenv(name)
        if value is None:
            raise SecretResolutionError(f"environment secret {name} is unavailable")
        return value


class ClientSecretProvider:
    """Adapter for injected cloud/Vault SDK clients; SDKs remain optional."""
    def __init__(self, scheme: str, client: Any, resolver: str) -> None:
        self.scheme, self.client, self.resolver = scheme, client, resolver

    async def resolve(self, secret_ref: str) -> str:
        method = getattr(self.client, self.resolver, None)
        if method is None:
            raise SecretResolutionError(f"{self.scheme} client does not implement {self.resolver}")
        value = method(secret_ref)
        if hasattr(value, "__await__"):
            value = await value
        if isinstance(value, dict):
            value = value.get("SecretString") or value.get("value") or value.get("data")
        if hasattr(value, "value"):
            value = value.value
        if not isinstance(value, str) or not value:
            raise SecretResolutionError(f"{self.scheme} returned no secret value")
        return value


class SecretProviderRegistry:
    def __init__(self, providers: list[SecretProvider] | None = None) -> None:
        self._providers = {provider.scheme: provider for provider in (providers or [EnvironmentSecretProvider()])}

    def register(self, provider: SecretProvider) -> None:
        self._providers[provider.scheme] = provider

    def supported_schemes(self) -> list[str]:
        return sorted(self._providers)

    async def resolve(self, secret_ref: str) -> str:
        if not isinstance(secret_ref, str) or "://" not in secret_ref:
            raise SecretResolutionError("secret_ref must use an explicit provider scheme")
        scheme = secret_ref.split("://", 1)[0].lower()
        provider = self._providers.get(scheme)
        if provider is None:
            raise SecretResolutionError(f"secret provider {scheme} is not configured")
        return await provider.resolve(secret_ref)

