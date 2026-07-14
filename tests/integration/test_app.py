"""
Integration tests for the Nexus application.
"""

import asyncio
from pathlib import Path

import pytest

from nexus.app import NexusApp
from nexus.config import NexusConfig
from nexus.domain.enums import MessageType, Priority
from nexus.domain.models import Message


class TestNexusApp:
    """Integration tests for NexusApp."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> NexusConfig:
        """Create test configuration."""
        return NexusConfig(
            device_id="nexus-test",
            name="Test Nexus",
            database={"path": str(tmp_path / "test.db")},
            server={"enabled": False},  # Disable API for tests
        )

    @pytest.fixture
    async def app(self, config: NexusConfig) -> NexusApp:
        """Create and start test app."""
        app = NexusApp(config)
        yield app
        if app.is_running:
            await app.stop()

    @pytest.mark.asyncio
    async def test_app_lifecycle(self, config: NexusConfig) -> None:
        """Test app start and stop."""
        app = NexusApp(config)

        assert not app.is_running

        await app.start()
        assert app.is_running
        assert app.uptime > 0

        await app.stop()
        assert not app.is_running

    @pytest.mark.asyncio
    async def test_app_components_initialized(self, config: NexusConfig) -> None:
        """Test that all components are initialized."""
        app = NexusApp(config)
        await app.start()

        try:
            assert app.router is not None
            assert app.channel_manager is not None
            assert app.fleet_manager is not None
        finally:
            await app.stop()

    @pytest.mark.asyncio
    async def test_app_status(self, config: NexusConfig) -> None:
        """Test app status reporting."""
        app = NexusApp(config)
        await app.start()

        try:
            status = await app.get_status()

            assert status["running"] is True
            assert status["device_id"] == "nexus-test"
            assert status["uptime"] >= 0
            assert "channels" in status
            assert "router" in status
            assert "fleet" in status
        finally:
            await app.stop()


class TestEndToEndRouting:
    """End-to-end routing tests."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> NexusConfig:
        """Create test configuration."""
        return NexusConfig(
            device_id="nexus-e2e",
            database={"path": str(tmp_path / "e2e.db")},
            server={"enabled": False},
        )

    @pytest.mark.asyncio
    async def test_message_routing_with_mock_channel(self, config: NexusConfig) -> None:
        """Test message routing through mock channel."""
        from nexus.channels.mock import MockChannel

        app = NexusApp(config)
        await app.start()

        try:
            # Add mock channel
            mock = MockChannel(name="test-mock")
            await mock.connect()
            app.router.register_channel(mock)

            # Create and route message
            msg = Message(
                src="nexus-e2e",
                dst="device-001",
                type=MessageType.DATA,
                pri=Priority.NORMAL,
                data={"test": "data"},
            )

            result = await app.router.route(msg)

            assert result.success
            assert len(mock.sent_messages) == 1

        finally:
            await app.stop()

    @pytest.mark.asyncio
    async def test_device_registration_flow(self, config: NexusConfig) -> None:
        """Test device registration through fleet manager."""
        from nexus.domain.enums import DeviceType

        app = NexusApp(config)
        await app.start()

        try:
            # Register device
            device = await app.fleet_manager.registry.register(
                device_id="momo-001",
                device_type=DeviceType.MOMO,
                name="Test MoMo",
            )

            assert device is not None
            assert device.id == "momo-001"

            # Verify in registry
            fetched = await app.fleet_manager.registry.get("momo-001")
            assert fetched is not None
            assert fetched.name == "Test MoMo"

        finally:
            await app.stop()

    @pytest.mark.asyncio
    async def test_alert_creation_flow(self, config: NexusConfig) -> None:
        """Test alert creation through fleet manager."""
        from nexus.fleet.alerts import AlertSeverity, AlertType

        app = NexusApp(config)
        await app.start()

        try:
            # Create alert
            alert = await app.fleet_manager.alerts.create(
                type=AlertType.HANDSHAKE_CAPTURED,
                severity=AlertSeverity.HIGH,
                title="Test Handshake",
                device_id="momo-001",
            )

            assert alert is not None
            assert alert.type == AlertType.HANDSHAKE_CAPTURED

            # Verify retrieval
            fetched = await app.fleet_manager.alerts.get(alert.id)
            assert fetched is not None
            assert fetched.title == "Test Handshake"

        finally:
            await app.stop()


class TestSecurityIntegration:
    """Security integration tests."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> NexusConfig:
        """Create test configuration."""
        return NexusConfig(
            device_id="nexus-sec",
            database={"path": str(tmp_path / "sec.db")},
            server={"enabled": False},
            security={"default_level": "encrypted"},
        )

    @pytest.mark.asyncio
    async def test_secure_message_envelope(self, config: NexusConfig) -> None:
        """Test message security envelope."""
        from nexus.security.envelope import SecurityLevel

        app = NexusApp(config)
        await app.start()

        try:
            # Create message
            msg = Message(
                src="nexus-sec",
                dst="device-001",
                type=MessageType.COMMAND,
                data={"cmd": "status"},
            )

            # Secure message
            envelope = await app._security_manager.secure_message(
                msg,
                level=SecurityLevel.ENCRYPTED,
            )

            assert envelope.lvl == SecurityLevel.ENCRYPTED
            assert envelope.sig != ""

            # Verify message
            valid, decrypted = await app._security_manager.verify_message(envelope)

            assert valid
            assert decrypted.src == "nexus-sec"

        finally:
            await app.stop()


class TestGeoIntegration:
    """Geofencing integration tests."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> NexusConfig:
        """Create test configuration."""
        return NexusConfig(
            device_id="nexus-geo",
            database={"path": str(tmp_path / "geo.db")},
            server={"enabled": False},
        )

    @pytest.mark.asyncio
    async def test_zone_event_detection(self, config: NexusConfig) -> None:
        """Test zone enter/exit event detection."""
        from nexus.geo.location import GPSCoordinate, Location
        from nexus.geo.manager import ZoneEventType
        from nexus.geo.zones import CircleZone

        app = NexusApp(config)
        await app.start()

        try:
            # Create zone
            zone = CircleZone(
                id="hq",
                name="Headquarters",
                center=GPSCoordinate(40.0, -74.0),
                radius=1000,
            )
            await app._geo_manager.add_zone(zone)

            # Device outside zone
            await app._geo_manager.update_location(
                "momo-001",
                Location(41.0, -74.0),
            )

            # Device enters zone
            events = await app._geo_manager.update_location(
                "momo-001",
                Location(40.0, -74.0),
            )

            assert len(events) == 1
            assert events[0].event_type == ZoneEventType.ENTER
            assert events[0].zone.id == "hq"

        finally:
            await app.stop()

