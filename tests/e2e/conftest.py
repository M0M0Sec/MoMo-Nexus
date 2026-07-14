"""
E2E Test Configuration.

Provides fixtures for E2E tests with disabled authentication.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from nexus.api.app import create_app
from nexus.config import NexusConfig


@pytest.fixture
def api_client():
    """
    Create test API client with authentication disabled.
    
    The test config disables auth so we can test endpoints
    without dealing with API key management.
    """
    # Create test config with auth disabled
    test_config = NexusConfig(
        device_id="nexus-test",
        name="Test Nexus",
    )
    test_config.server.auth_enabled = False

    # Create app with test config
    app = create_app(config=test_config)

    # Mock the app state managers with async methods
    app.state.fleet_manager = MagicMock()
    app.state.channel_manager = MagicMock()
    app.state.router = MagicMock()

    # Setup ASYNC mock returns for fleet_manager (these methods are awaited)
    app.state.fleet_manager.registry.get_all = AsyncMock(return_value=[])
    app.state.fleet_manager.registry.get = AsyncMock(return_value=None)
    app.state.fleet_manager.registry.get_by_status = AsyncMock(return_value=[])
    app.state.fleet_manager.registry.get_by_type = AsyncMock(return_value=[])
    app.state.fleet_manager.registry.get_stats = AsyncMock(return_value={
        "total": 0,
        "online": 0,
        "offline": 0,
        "unknown": 0,
    })

    app.state.fleet_manager.alerts.get_all = AsyncMock(return_value=[])
    app.state.fleet_manager.alerts.get = AsyncMock(return_value=None)
    app.state.fleet_manager.alerts.get_stats = AsyncMock(return_value={
        "total": 0,
        "unacknowledged": 0,
    })

    app.state.fleet_manager.monitor.get_health = AsyncMock(return_value=None)
    app.state.fleet_manager.get_stats = AsyncMock(return_value={})
    app.state.fleet_manager.get_dashboard_data = AsyncMock(return_value={
        "devices": [],
        "alerts": [],
        "channels": {},
        "stats": {},
    })

    # Setup sync mock returns for channel_manager (these are not awaited)
    app.state.channel_manager.get_status.return_value = {
        "lora": {"connected": False, "available": False},
        "wifi": {"connected": False, "available": False},
        "bluetooth": {"connected": False, "available": False},
    }
    app.state.channel_manager.get_channel.return_value = None

    yield TestClient(app)


@pytest.fixture
def auth_headers():
    """
    Authentication headers for E2E tests.
    
    With auth disabled in test config, these headers are optional
    but provided for API format consistency.
    """
    return {"X-API-Key": "test-api-key"}


@pytest.fixture
def api_client_with_auth():
    """
    Create test API client with authentication ENABLED.
    
    Use this fixture when you specifically want to test
    authentication behavior.
    """
    test_config = NexusConfig(
        device_id="nexus-test",
        name="Test Nexus",
    )
    test_config.server.auth_enabled = True
    test_config.server.api_key = "test-secret-key"

    app = create_app(config=test_config)
    app.state.api_key = "test-secret-key"

    # Mock managers with async methods
    app.state.fleet_manager = MagicMock()
    app.state.channel_manager = MagicMock()
    app.state.router = MagicMock()

    # Async mocks
    app.state.fleet_manager.registry.get_all = AsyncMock(return_value=[])
    app.state.fleet_manager.registry.get = AsyncMock(return_value=None)
    app.state.fleet_manager.registry.get_stats = AsyncMock(return_value={})
    app.state.fleet_manager.alerts.get_all = AsyncMock(return_value=[])
    app.state.fleet_manager.alerts.get = AsyncMock(return_value=None)
    app.state.fleet_manager.alerts.get_stats = AsyncMock(return_value={})

    yield TestClient(app)


@pytest.fixture
def valid_auth_headers():
    """Valid auth headers for api_client_with_auth fixture."""
    return {"X-API-Key": "test-secret-key"}
