"""
Tests for fleet management.
"""

from datetime import datetime, timedelta

import pytest

from nexus.config import NexusConfig
from nexus.core.events import EventBus, EventType
from nexus.domain.enums import DeviceStatus, DeviceType, MessageType, Priority
from nexus.domain.models import Device, Message
from nexus.fleet.alerts import AlertManager, AlertSeverity, AlertType
from nexus.fleet.monitor import HealthMonitor
from nexus.fleet.registry import DeviceRegistry


class TestDeviceRegistry:
    """Tests for DeviceRegistry."""

    @pytest.fixture
    def registry(self) -> DeviceRegistry:
        """Create registry."""
        config = NexusConfig()
        event_bus = EventBus()
        return DeviceRegistry(config=config, event_bus=event_bus)

    @pytest.mark.asyncio
    async def test_register_device(self, registry: DeviceRegistry) -> None:
        """Test device registration."""
        device = await registry.register(
            device_id="momo-001",
            device_type=DeviceType.MOMO,
            name="Test MoMo",
        )

        assert device is not None
        assert device.id == "momo-001"
        assert device.type == DeviceType.MOMO
        assert device.status == DeviceStatus.ONLINE

    @pytest.mark.asyncio
    async def test_get_device(self, registry: DeviceRegistry) -> None:
        """Test getting device."""
        await registry.register("momo-001", DeviceType.MOMO)

        device = await registry.get("momo-001")
        assert device is not None
        assert device.id == "momo-001"

        missing = await registry.get("nonexistent")
        assert missing is None

    @pytest.mark.asyncio
    async def test_get_by_type(self, registry: DeviceRegistry) -> None:
        """Test getting devices by type."""
        await registry.register("momo-001", DeviceType.MOMO)
        await registry.register("momo-002", DeviceType.MOMO)
        await registry.register("ghost-001", DeviceType.GHOSTBRIDGE)

        momos = await registry.get_by_type(DeviceType.MOMO)
        assert len(momos) == 2

        ghosts = await registry.get_by_type(DeviceType.GHOSTBRIDGE)
        assert len(ghosts) == 1

    @pytest.mark.asyncio
    async def test_update_device(self, registry: DeviceRegistry) -> None:
        """Test updating device."""
        await registry.register("momo-001")

        updated = await registry.update(
            "momo-001",
            status=DeviceStatus.SLEEPING,
            battery=85,
        )

        assert updated is not None
        assert updated.status == DeviceStatus.SLEEPING
        assert updated.battery == 85

    @pytest.mark.asyncio
    async def test_unregister_device(self, registry: DeviceRegistry) -> None:
        """Test unregistering device."""
        await registry.register("momo-001")

        result = await registry.unregister("momo-001")
        assert result is True

        device = await registry.get("momo-001")
        assert device is None

    @pytest.mark.asyncio
    async def test_blacklist(self, registry: DeviceRegistry) -> None:
        """Test blacklist functionality."""
        registry.add_to_blacklist("bad-device")

        device = await registry.register("bad-device")
        assert device is None

        assert not registry.is_allowed("bad-device")

    @pytest.mark.asyncio
    async def test_register_from_hello(self, registry: DeviceRegistry) -> None:
        """Test registration from HELLO message."""
        message = Message(
            src="momo-001",
            type=MessageType.HELLO,
            data={
                "type": "momo",
                "version": "1.5.0",
                "capabilities": ["wifi_capture", "ble_scan"],
                "channels": ["lora", "wifi"],
                "battery": 85,
            },
        )

        device = await registry.register_from_hello(message)

        assert device is not None
        assert device.id == "momo-001"
        assert device.type == DeviceType.MOMO
        assert device.version == "1.5.0"
        assert "wifi_capture" in device.capabilities

    @pytest.mark.asyncio
    async def test_get_stats(self, registry: DeviceRegistry) -> None:
        """Test getting statistics."""
        await registry.register("dev-1")
        await registry.register("dev-2")

        await registry.set_status("dev-2", DeviceStatus.OFFLINE)

        stats = await registry.get_stats()

        assert stats["total"] == 2
        assert stats["online"] >= 1


class TestHealthMonitor:
    """Tests for HealthMonitor."""

    @pytest.fixture
    def monitor(self) -> HealthMonitor:
        """Create health monitor."""
        config = NexusConfig()
        event_bus = EventBus()
        registry = DeviceRegistry(config=config, event_bus=event_bus)
        return HealthMonitor(registry=registry, config=config, event_bus=event_bus)

    @pytest.mark.asyncio
    async def test_process_heartbeat(self, monitor: HealthMonitor) -> None:
        """Test processing heartbeat."""
        await monitor._registry.register("momo-001")

        await monitor.process_heartbeat("momo-001", {"battery": 85, "cpu": 45})

        health = await monitor.get_health("momo-001")
        assert health is not None
        assert health.battery == 85
        assert health.cpu == 45
        assert health.consecutive_misses == 0

    @pytest.mark.asyncio
    async def test_missed_heartbeats_counted_every_check(self, monitor: HealthMonitor) -> None:
        """Roadmap 2.7: consecutive_misses must increment on EVERY missed check (not just
        the ONLINE→OFFLINE transition) and be mutated under the lock."""
        await monitor._registry.register("momo-001")
        dev = await monitor._registry.get("momo-001")
        dev.status = DeviceStatus.ONLINE
        dev.last_seen = datetime.now() - timedelta(
            seconds=monitor._heartbeat_timeout + 100
        )

        await monitor._check_devices()  # transition → OFFLINE, miss #1
        health = await monitor.get_health("momo-001")
        assert health.consecutive_misses == 1

        await monitor._check_devices()  # already OFFLINE, but still a miss → #2
        assert health.consecutive_misses == 2

    @pytest.mark.asyncio
    async def test_health_score(self, monitor: HealthMonitor) -> None:
        """Test health score calculation."""
        await monitor._registry.register("momo-001")

        # Good health
        await monitor.process_heartbeat("momo-001", {"battery": 100})
        health = await monitor.get_health("momo-001")
        assert health.health_score >= 90

        # Low battery should decrease score
        await monitor.process_heartbeat("momo-002", {"battery": 10})
        health2 = await monitor.get_health("momo-002")
        assert health2 is not None
        assert health2.health_score < health.health_score

    @pytest.mark.asyncio
    async def test_is_healthy(self, monitor: HealthMonitor) -> None:
        """Test health check."""
        await monitor._registry.register("momo-001")
        await monitor.process_heartbeat("momo-001", {"battery": 80})

        healthy = await monitor.is_healthy("momo-001")
        assert healthy is True

    @pytest.mark.asyncio
    async def test_start_stop(self, monitor: HealthMonitor) -> None:
        """Test monitor lifecycle."""
        await monitor.start()
        assert monitor._running is True

        await monitor.stop()
        assert monitor._running is False


class TestAlertManager:
    """Tests for AlertManager."""

    @pytest.fixture
    def alerts(self) -> AlertManager:
        """Create alert manager."""
        return AlertManager()

    @pytest.mark.asyncio
    async def test_create_alert(self, alerts: AlertManager) -> None:
        """Test creating alert."""
        alert = await alerts.create(
            type=AlertType.HANDSHAKE_CAPTURED,
            severity=AlertSeverity.HIGH,
            title="Handshake captured",
            message="Captured handshake for CORP-WIFI",
            device_id="momo-001",
        )

        assert alert is not None
        assert alert.type == AlertType.HANDSHAKE_CAPTURED
        assert alert.severity == AlertSeverity.HIGH
        assert not alert.acknowledged

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self, alerts: AlertManager) -> None:
        """Test acknowledging alert."""
        alert = await alerts.create(
            type=AlertType.DEVICE_OFFLINE,
            severity=AlertSeverity.MEDIUM,
            title="Device offline",
        )

        result = await alerts.acknowledge(alert.id, "admin")

        assert result is True

        updated = await alerts.get(alert.id)
        assert updated.acknowledged is True
        assert updated.acknowledged_by == "admin"

    @pytest.mark.asyncio
    async def test_get_alerts(self, alerts: AlertManager) -> None:
        """Test getting alerts."""
        await alerts.create(AlertType.CUSTOM, AlertSeverity.LOW, "Alert 1")
        await alerts.create(AlertType.CUSTOM, AlertSeverity.HIGH, "Alert 2")
        await alerts.create(AlertType.CUSTOM, AlertSeverity.CRITICAL, "Alert 3")

        all_alerts = await alerts.get_all()
        assert len(all_alerts) == 3

        critical = await alerts.get_by_severity(AlertSeverity.CRITICAL)
        assert len(critical) == 1

    @pytest.mark.asyncio
    async def test_get_unacknowledged(self, alerts: AlertManager) -> None:
        """Test getting unacknowledged alerts."""
        alert1 = await alerts.create(AlertType.CUSTOM, AlertSeverity.LOW, "A1")
        alert2 = await alerts.create(AlertType.CUSTOM, AlertSeverity.LOW, "A2")

        await alerts.acknowledge(alert1.id)

        unacked = await alerts.get_unacknowledged()
        assert len(unacked) == 1
        assert unacked[0].id == alert2.id

    @pytest.mark.asyncio
    async def test_create_from_message(self, alerts: AlertManager) -> None:
        """Test creating alert from message."""
        message = Message(
            src="momo-001",
            type=MessageType.ALERT,
            data={
                "type": "handshake_captured",
                "severity": "high",
                "title": "Handshake from CORP-WIFI",
                "data": {
                    "ssid": "CORP-WIFI",
                    "bssid": "AA:BB:CC:DD:EE:FF",
                },
            },
        )

        alert = await alerts.create_from_message(message)

        assert alert.type == AlertType.HANDSHAKE_CAPTURED
        assert alert.severity == AlertSeverity.HIGH
        assert alert.device_id == "momo-001"

    @pytest.mark.asyncio
    async def test_handler_notification(self, alerts: AlertManager) -> None:
        """Test alert handlers are notified."""
        received = []

        async def handler(alert):
            received.append(alert)

        alerts.add_handler(handler)

        await alerts.create(AlertType.CUSTOM, AlertSeverity.LOW, "Test")

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_get_stats(self, alerts: AlertManager) -> None:
        """Test getting statistics."""
        await alerts.create(AlertType.DEVICE_OFFLINE, AlertSeverity.MEDIUM, "A1")
        await alerts.create(AlertType.DEVICE_OFFLINE, AlertSeverity.MEDIUM, "A2")
        await alerts.create(AlertType.HANDSHAKE_CAPTURED, AlertSeverity.HIGH, "A3")

        stats = await alerts.get_stats()

        assert stats["total"] == 3
        assert stats["unacknowledged"] == 3
        assert AlertSeverity.MEDIUM.value in str(stats["by_severity"])



# ---------------------------------------------------------------------------
# CommandDispatcher — _pending leak fixes (remediation plan 2.3)
# ---------------------------------------------------------------------------
class _FakeRouteResult:
    def __init__(self, success: bool) -> None:
        self.success = success


class _FakeRouter:
    def __init__(self, success: bool = True, raises: bool = False) -> None:
        self._success = success
        self._raises = raises

    async def route(self, message):
        if self._raises:
            raise RuntimeError("route boom")
        return _FakeRouteResult(self._success)


class TestCommandDispatcherLeaks:
    async def _dispatcher(self, router):
        from nexus.fleet.commands import CommandDispatcher
        config = NexusConfig()
        event_bus = EventBus()
        registry = DeviceRegistry(config=config, event_bus=event_bus)
        await registry.register("momo-001", DeviceType.MOMO)
        return CommandDispatcher(
            router=router, registry=registry, config=config, event_bus=event_bus
        )

    @pytest.mark.asyncio
    async def test_failed_send_does_not_leak_pending(self):
        d = await self._dispatcher(_FakeRouter(success=False))
        result = await d.dispatch("momo-001", "ping", wait=False)
        assert result.success is False
        assert len(d._pending) == 0  # cleaned up, not leaked

    @pytest.mark.asyncio
    async def test_exception_does_not_leak_pending(self):
        d = await self._dispatcher(_FakeRouter(raises=True))
        result = await d.dispatch("momo-001", "ping", wait=False)
        assert result.success is False
        assert len(d._pending) == 0

    @pytest.mark.asyncio
    async def test_sweep_expired_removes_stale_pending(self):
        d = await self._dispatcher(_FakeRouter(success=True))
        result = await d.dispatch("momo-001", "ping", wait=False)
        assert result.pending is True
        assert len(d._pending) == 1  # legitimately pending (fire-and-forget)

        # Age the pending command past its timeout, then sweep.
        for pending in d._pending.values():
            pending.created_at = datetime.now() - timedelta(
                seconds=pending.command.timeout + 100
            )
        swept = await d.sweep_expired()
        assert swept == 1
        assert len(d._pending) == 0
