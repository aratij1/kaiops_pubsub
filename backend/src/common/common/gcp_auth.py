from __future__ import annotations

from common.logging import get_logger

logger = get_logger(__name__)


def get_google_bearer_token(*, scopes: list[str] | None = None) -> str | None:
    """Fetch a bearer token from Application Default Credentials.

    Returns None (never raises) when no credentials are available, so callers
    can fall back to a local/offline code path instead of crashing.
    """
    try:
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(scopes=scopes or ["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        token = str(getattr(credentials, "token", "") or "").strip()
        return token or None
    except Exception as exc:
        logger.warning("failed to obtain Google Application Default Credentials", extra={"error": str(exc)})
        return None
