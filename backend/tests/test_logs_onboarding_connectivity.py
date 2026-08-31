import importlib.util
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

def load_monitoring_app_module():
    module_path = Path("backend/src/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

module = load_monitoring_app_module()

def test_sanitize_url_credentials():
    url_with_pass = "http://admin:secret123@host.docker.internal:9200"
    sanitized = module._sanitize_url_credentials(url_with_pass)
    assert sanitized == "http://admin@host.docker.internal:9200"
    
    url_no_pass = "http://admin@host.docker.internal:9200"
    assert module._sanitize_url_credentials(url_no_pass) == url_no_pass

@pytest.mark.asyncio
async def test_check_logs_connectivity_local_path_success(tmp_path):
    test_file = tmp_path / "app.log"
    test_file.write_text("log line")
    
    ok, msg = await module.check_logs_connectivity(str(test_file))
    assert ok is True
    assert "file is readable" in msg

@pytest.mark.asyncio
async def test_check_logs_connectivity_local_path_missing():
    ok, msg = await module.check_logs_connectivity("non_existent_file_path.log")
    assert ok is False
    assert "Path does not exist" in msg

@pytest.mark.asyncio
async def test_check_logs_connectivity_local_dir_unreadable():
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("os.access", return_value=False):
        ok, msg = await module.check_logs_connectivity("some_unreadable_directory")
        assert ok is False
        assert "is not readable" in msg

@pytest.mark.asyncio
async def test_check_logs_connectivity_local_file_unreadable():
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=False), \
         patch("builtins.open", side_effect=PermissionError("Permission denied")):
        ok, msg = await module.check_logs_connectivity("some_unreadable_file.log")
        assert ok is False
        assert "is not readable" in msg

@pytest.mark.asyncio
async def test_check_logs_connectivity_opensearch_success():
    mock_res = MagicMock()
    mock_res.status_code = 200
    
    # Mock Response for httpx client
    async def mock_post(*args, **kwargs):
        return mock_res
        
    with patch("httpx.AsyncClient.post", side_effect=mock_post) as mock_post_call:
        ok, msg = await module.check_logs_connectivity("http://opensearch:9200")
        assert ok is True
        assert "Connected to OpenSearch" in msg
        mock_post_call.assert_called_once()

@pytest.mark.asyncio
async def test_check_logs_connectivity_opensearch_unauthorized():
    mock_res = MagicMock()
    mock_res.status_code = 401
    
    # Mock Response for httpx client
    async def mock_post(*args, **kwargs):
        return mock_res
        
    with patch("httpx.AsyncClient.post", side_effect=mock_post) as mock_post_call:
        ok, msg = await module.check_logs_connectivity("http://admin:wrong_pass@opensearch:9200")
        assert ok is False
        assert "Authentication failed" in msg
        mock_post_call.assert_called_once()

@pytest.mark.asyncio
async def test_check_logs_connectivity_opensearch_exception_redacts_password():
    async def mock_post_fail(*args, **kwargs):
        raise ConnectionError("Failed to connect to http://admin:CLAUDE_TEST_SECRET_PASSWORD_123@host:9200")
        
    with patch("httpx.AsyncClient.post", side_effect=mock_post_fail):
        ok, msg = await module.check_logs_connectivity("http://admin:CLAUDE_TEST_SECRET_PASSWORD_123@host:9200")
        assert ok is False
        assert "CLAUDE_TEST_SECRET_PASSWORD_123" not in msg
        assert "******" in msg
