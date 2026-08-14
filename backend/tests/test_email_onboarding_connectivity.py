import importlib.util
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
import imaplib

def load_monitoring_app_module():
    module_path = Path("backend/src/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

module = load_monitoring_app_module()

def test_parse_email_url_complete():
    url = "imaps://user%40example.com:pass%20123@imap.example.com:993/INBOX"
    config = module.parse_email_url(url)
    assert config.host == "imap.example.com"
    assert config.port == 993
    assert config.username == "user@example.com"
    assert config.password == "pass 123"
    assert config.mailbox == "INBOX"
    assert config.use_ssl is True

def test_parse_email_url_fallback():
    url = "imap://imap.example.com/CUSTOM"
    config = module.parse_email_url(url)
    assert config.host == "imap.example.com"
    assert config.port == 143
    assert config.mailbox == "CUSTOM"
    assert config.use_ssl is False

def test_sanitize_email_url_strips_password():
    url = "imaps://user%40example.com:password123@imap.example.com:993/INBOX"
    sanitized = module.sanitize_email_url(url)
    assert sanitized == "imaps://user%40example.com@imap.example.com:993/INBOX"
    assert "password123" not in sanitized

    # URL without password should remain intact
    url_no_pass = "imaps://user%40example.com@imap.example.com:993/INBOX"
    assert module.sanitize_email_url(url_no_pass) == url_no_pass

def test_check_imap_connectivity_success():
    mock_conn = MagicMock()
    mock_conn_cls = MagicMock(return_value=mock_conn)
    
    with patch("imaplib.IMAP4_SSL", mock_conn_cls):
        from monitoring_adapter.email_ingestion import ImapConfig
        config = ImapConfig(
            host="imap.example.com",
            port=993,
            username="user",
            password="pwd",
            use_ssl=True
        )
        ok, msg = module.check_imap_connectivity(config)
        assert ok is True
        assert msg == "Connected"
        mock_conn.login.assert_called_once_with("user", "pwd")
        mock_conn.select.assert_called_once_with("INBOX")

def test_check_imap_connectivity_auth_fail():
    mock_conn = MagicMock()
    mock_conn.login.side_effect = imaplib.IMAP4.error("Invalid credentials")
    mock_conn_cls = MagicMock(return_value=mock_conn)
    
    with patch("imaplib.IMAP4_SSL", mock_conn_cls):
        from monitoring_adapter.email_ingestion import ImapConfig
        config = ImapConfig(
            host="imap.example.com",
            port=993,
            username="user",
            password="pwd",
            use_ssl=True
        )
        ok, msg = module.check_imap_connectivity(config)
        assert ok is False
        assert "Authentication failed" in msg


def test_post_onboarding_connectivity_fallback():
    mock_conn = MagicMock()
    mock_conn_cls = MagicMock(return_value=mock_conn)
    
    with patch("imaplib.IMAP4_SSL", mock_conn_cls), \
         patch.object(module, "EMAIL_IMAP_HOST", "imap.env-test.com"), \
         patch.object(module, "EMAIL_IMAP_PORT", 993), \
         patch.object(module, "EMAIL_IMAP_USER", "env-user"), \
         patch.object(module, "EMAIL_IMAP_PASSWORD", "env-pass"), \
         patch.object(module, "EMAIL_IMAP_USE_SSL", True), \
         patch.object(module, "save_onboarding_connectivity") as mock_save, \
         patch.object(module, "persist_onboarding_connectivity") as mock_persist:
         
        mock_save.return_value = {
            "project": {"name": "test"},
            "provider_statuses": {"email": {"ok": True, "message": "Connected"}},
            "email_url": ""
        }
        
        # Call connectivity endpoint or check_imap_connectivity manually
        from monitoring_adapter.email_ingestion import ImapConfig
        config = ImapConfig(
            host=module.EMAIL_IMAP_HOST,
            port=module.EMAIL_IMAP_PORT,
            username=module.EMAIL_IMAP_USER,
            password=module.EMAIL_IMAP_PASSWORD,
            use_ssl=module.EMAIL_IMAP_USE_SSL,
        )
        ok, msg = module.check_imap_connectivity(config)
        assert ok is True
        assert msg == "Connected"


def test_middleware_url_credential_sanitization():
    from common.service import _mask_sensitive_fields
    payload = {
        "email_url": "imaps://testuser%40example.com:testpass@imap.example.com:993/INBOX",
        "prometheus_url": "http://admin:secret123@prometheus:9090",
        "normal_field": "some-value",
        "nested": {
            "token": "sensitive-token-xyz",
            "logs_url": "https://user:pass123@logs.example.com"
        }
    }
    sanitized = _mask_sensitive_fields(payload)
    assert sanitized["email_url"] == "imaps://testuser%40example.com@imap.example.com:993/INBOX"
    assert sanitized["prometheus_url"] == "http://admin@prometheus:9090"
    assert sanitized["normal_field"] == "some-value"
    assert sanitized["nested"]["token"] == "***"
    assert sanitized["nested"]["logs_url"] == "https://user@logs.example.com"


