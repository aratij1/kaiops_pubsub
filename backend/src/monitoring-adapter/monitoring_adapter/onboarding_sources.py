from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


def normalize_http_endpoint(value: str, field_name: str) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid http(s) URL")
    return endpoint


def normalize_email_endpoint(value: str) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https", "imap", "imaps"} or not parsed.netloc:
        raise ValueError("email_url must be a valid http(s), imap, or imaps URL")
    return endpoint


class OnboardingMonitoringSource(BaseModel):
    provider: str
    endpoint_url: str = ""
    signal_types: list[str] = Field(default_factory=list)
    auth_type: str = "none"
    secret_ref: str = ""
    enabled: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> "OnboardingMonitoringSource":
        self.provider = str(self.provider or "").strip().lower().replace(" ", "_")
        if not self.provider: raise ValueError("monitoring_sources.provider is required")
        self.endpoint_url = normalize_http_endpoint(self.endpoint_url, "monitoring_sources.endpoint_url")
        self.signal_types = list(dict.fromkeys(str(item or "").strip().lower() for item in self.signal_types if str(item or "").strip()))
        self.auth_type = str(self.auth_type or "none").strip().lower()
        if self.auth_type not in {"none", "basic", "bearer", "api_key", "oauth2", "managed_identity"}: raise ValueError("monitoring_sources.auth_type is invalid")
        self.secret_ref = str(self.secret_ref or "").strip()
        if self.auth_type != "none" and not self.secret_ref: raise ValueError("monitoring_sources.secret_ref is required when authentication is enabled")
        return self
