"""
Unit tests for notification system.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.notifications.manager import NotificationManager
from nexus.notifications.ntfy import NotificationResult, NtfyClient, NtfyConfig, NtfyPriority


class TestNtfyConfig:
    """Tests for NtfyConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = NtfyConfig()

        assert config.enabled is False
        assert config.server_url == "https://ntfy.sh"
        assert config.topic == "momo-alerts"
        assert config.access_token is None
        assert config.min_severity == "medium"

    def test_topic_url(self):
        """Test topic URL generation."""
        config = NtfyConfig(server_url="https://ntfy.example.com", topic="my-alerts")

        assert config.topic_url == "https://ntfy.example.com/my-alerts"

    def test_topic_url_trailing_slash(self):
        """Test topic URL with trailing slash in server URL."""
        config = NtfyConfig(server_url="https://ntfy.example.com/", topic="my-alerts")

        assert config.topic_url == "https://ntfy.example.com/my-alerts"


class TestNtfyClient:
    """Tests for NtfyClient."""

    def test_severity_priority_mapping(self):
        """Test severity to priority mapping."""
        assert NtfyClient.SEVERITY_PRIORITY_MAP["critical"] == NtfyPriority.MAX
        assert NtfyClient.SEVERITY_PRIORITY_MAP["high"] == NtfyPriority.HIGH
        assert NtfyClient.SEVERITY_PRIORITY_MAP["medium"] == NtfyPriority.DEFAULT
        assert NtfyClient.SEVERITY_PRIORITY_MAP["low"] == NtfyPriority.LOW
        assert NtfyClient.SEVERITY_PRIORITY_MAP["info"] == NtfyPriority.MIN

    def test_alert_emoji_mapping(self):
        """Test alert type to emoji mapping."""
        assert NtfyClient.ALERT_EMOJI_MAP["handshake_captured"] == "handshake"
        assert NtfyClient.ALERT_EMOJI_MAP["password_cracked"] == "key"
        assert NtfyClient.ALERT_EMOJI_MAP["credential_captured"] == "lock"

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        """Test send when notifications are disabled."""
        config = NtfyConfig(enabled=False)
        client = NtfyClient(config)

        result = await client.send("Test message")

        assert result.success is False
        assert "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_alert_below_min_severity(self):
        """Test send_alert filters by minimum severity."""
        config = NtfyConfig(enabled=True, min_severity="high")
        client = NtfyClient(config)

        result = await client.send_alert(
            alert_type="test",
            severity="medium",  # Below min_severity of "high"
            title="Test",
            message="Test message",
        )

        assert result.success is False
        assert "severity" in result.error.lower()

    @pytest.mark.asyncio
    async def test_build_headers_with_token(self):
        """Test header building with access token."""
        config = NtfyConfig(enabled=True, access_token="tk_test_token")
        client = NtfyClient(config)

        headers = client._build_headers()

        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer tk_test_token"

    @pytest.mark.asyncio
    async def test_build_headers_with_basic_auth(self):
        """Test header building with basic auth."""
        config = NtfyConfig(enabled=True, username="user", password="pass")
        client = NtfyClient(config)

        headers = client._build_headers()

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")


class TestNotificationManager:
    """Tests for NotificationManager."""

    def test_ntfy_not_enabled_by_default(self):
        """Test that Ntfy is not enabled by default."""
        manager = NotificationManager()

        assert manager.ntfy_enabled is False

    def test_configure_ntfy_enabled(self):
        """Test configuring Ntfy when enabled."""
        manager = NotificationManager()
        config = NtfyConfig(enabled=True, topic="test-topic")

        manager.configure_ntfy(config)

        assert manager.ntfy_enabled is True
        assert manager._ntfy is not None
        assert manager._ntfy.config.topic == "test-topic"

    def test_configure_ntfy_disabled(self):
        """Test configuring Ntfy when disabled."""
        manager = NotificationManager()
        config = NtfyConfig(enabled=False)

        manager.configure_ntfy(config)

        assert manager.ntfy_enabled is False
        assert manager._ntfy is None

    @pytest.mark.asyncio
    async def test_test_ntfy_not_configured(self):
        """Test testing Ntfy when not configured."""
        manager = NotificationManager()

        result = await manager.test_ntfy()

        assert result["success"] is False
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_notify_returns_false_when_no_channels(self):
        """Test notify returns False when no channels configured."""
        manager = NotificationManager()

        success = await manager.notify("Test message")

        assert success is False

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing manager."""
        manager = NotificationManager()
        config = NtfyConfig(enabled=True)
        manager.configure_ntfy(config)

        # Should not raise
        await manager.close()


class TestNtfyPriority:
    """Tests for NtfyPriority enum."""

    def test_priority_values(self):
        """Test priority enum values."""
        assert NtfyPriority.MAX.value == "max"
        assert NtfyPriority.HIGH.value == "high"
        assert NtfyPriority.DEFAULT.value == "default"
        assert NtfyPriority.LOW.value == "low"
        assert NtfyPriority.MIN.value == "min"


class TestNotificationResult:
    """Tests for NotificationResult."""

    def test_success_result(self):
        """Test successful notification result."""
        result = NotificationResult(success=True, message_id="msg123")

        assert result.success is True
        assert result.message_id == "msg123"
        assert result.error is None

    def test_failure_result(self):
        """Test failed notification result."""
        result = NotificationResult(success=False, error="Connection failed")

        assert result.success is False
        assert result.error == "Connection failed"
        assert result.message_id is None

