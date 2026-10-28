import pytest
from backend.app.main import nebius_client

@pytest.fixture(autouse=True)
def configure_mock_mode_for_tests(monkeypatch):
    """Ensure automated tests run in deterministic mock mode without requiring network calls or consuming tokens."""
    original_mock = nebius_client.mock_mode
    original_client = nebius_client.client
    original_key = nebius_client.api_key

    nebius_client.mock_mode = True
    nebius_client.client = None
    nebius_client.api_key = "mock_key"

    yield

    nebius_client.mock_mode = original_mock
    nebius_client.client = original_client
    nebius_client.api_key = original_key
