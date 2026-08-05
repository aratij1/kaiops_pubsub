import pytest
from pydantic import ValidationError

from api_gateway.oidc import OidcTokenValidator
from common.config import Settings


def test_production_rejects_local_password_authentication() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=oidc"):
        Settings(ENVIRONMENT="production", AUTH_MODE="local")


def test_production_accepts_complete_https_oidc_configuration() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        AUTH_MODE="oidc",
        OIDC_ISSUER="https://login.example.com/tenant/v2.0",
        OIDC_AUDIENCE="api://kaiops",
        OIDC_CLIENT_ID="kaiops-spa",
    )
    assert settings.auth_mode == "oidc"


def test_oidc_roles_are_explicitly_mapped_to_kaiops_roles() -> None:
    settings = Settings(
        ENVIRONMENT="test",
        AUTH_MODE="oidc",
        OIDC_ROLE_CLAIM="realm_access.roles",
        OIDC_ROLE_MAPPINGS='{"ops-admin": "Administrator"}',
    )
    validator = OidcTokenValidator(settings)
    assert validator._role({"realm_access": {"roles": ["ops-admin"]}}) == "Administrator"
