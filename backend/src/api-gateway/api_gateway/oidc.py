from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import HTTPException

from common.config import Settings
from common.tenant_identity import require_tenant_id
from common.authorization import OperationalRole

KAIOPS_ROLES = {
    *(role.value for role in OperationalRole),
    "Administrator", "Executive", "L3 Engineer", "L2 Engineer", "L1 Operator",
}


class OidcTokenValidator:
    """Cached OIDC discovery/JWKS validator for Entra ID and Keycloak."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks: dict[str, Any] = {}
        self._expires_at = datetime.min.replace(tzinfo=UTC)
        self._lock = asyncio.Lock()

    async def _keys(self) -> dict[str, Any]:
        if self._jwks and datetime.now(UTC) < self._expires_at:
            return self._jwks
        async with self._lock:
            if self._jwks and datetime.now(UTC) < self._expires_at:
                return self._jwks
            issuer = self.settings.oidc_issuer.rstrip("/")
            async with httpx.AsyncClient(timeout=8.0) as client:
                discovery = (await client.get(f"{issuer}/.well-known/openid-configuration")).raise_for_status().json()
                if str(discovery.get("issuer") or "").rstrip("/") != issuer:
                    raise HTTPException(status_code=503, detail="OIDC discovery issuer mismatch")
                jwks_uri = str(discovery.get("jwks_uri") or "")
                if not jwks_uri.startswith("https://"):
                    raise HTTPException(status_code=503, detail="OIDC JWKS endpoint is invalid")
                document = (await client.get(jwks_uri)).raise_for_status().json()
            self._jwks = {str(key.get("kid")): key for key in document.get("keys", []) if isinstance(key, dict) and key.get("kid")}
            self._expires_at = datetime.now(UTC) + timedelta(seconds=max(60, self.settings.oidc_jwks_cache_seconds))
            return self._jwks

    def _claim(self, claims: dict[str, Any], path: str) -> Any:
        current: Any = claims
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _role(self, claims: dict[str, Any]) -> str:
        raw = self._claim(claims, self.settings.oidc_role_claim)
        values = raw if isinstance(raw, list) else [raw] if raw else []
        try:
            mappings = json.loads(self.settings.oidc_role_mappings or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="OIDC role mapping configuration is invalid") from exc
        for value in values:
            mapped = mappings.get(str(value), str(value)) if isinstance(mappings, dict) else str(value)
            if mapped in KAIOPS_ROLES:
                return mapped
        raise HTTPException(status_code=403, detail="Identity has no mapped KaiOps role")

    async def validate(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = str(header.get("alg") or "")
            if algorithm not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}:
                raise HTTPException(status_code=401, detail="OIDC token algorithm is not allowed")
            key_data = (await self._keys()).get(str(header.get("kid") or ""))
            if key_data is None:
                self._expires_at = datetime.min.replace(tzinfo=UTC)
                key_data = (await self._keys()).get(str(header.get("kid") or ""))
            if key_data is None:
                raise HTTPException(status_code=401, detail="OIDC signing key was not found")
            claims = jwt.decode(
                token,
                jwt.PyJWK.from_dict(key_data).key,
                algorithms=[algorithm],
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer.rstrip("/"),
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            return {
                **claims,
                "type": "access",
                "external": True,
                "role": self._role(claims),
                "tenant_id": require_tenant_id(
                    self._claim(claims, self.settings.oidc_tenant_claim),
                    source=f"OIDC claim {self.settings.oidc_tenant_claim}",
                ),
                "jti": str(claims.get("jti") or claims.get("oid") or claims["sub"]),
                "sid": "",
            }
        except HTTPException:
            raise
        except (jwt.PyJWTError, httpx.HTTPError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="OIDC access token validation failed") from exc
