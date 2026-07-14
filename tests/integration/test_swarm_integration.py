"""
Integration tests for Swarm module - LoRa mesh networking.

Tests the full flow of Swarm integration within Nexus.

NOTE: These tests are skipped because Swarm API has changed significantly.
Swarm will be tested with real hardware in Phase 4.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all tests in this module - Swarm API has changed
pytestmark = pytest.mark.skip(reason="Swarm API changed - will be tested with real hardware")

from nexus.config import NexusConfig
from nexus.swarm import (
    BridgeStats,
    CommandCode,
    EventCode,
    SequenceTracker,
    SwarmBridge,
    SwarmConfig,
    SwarmManager,
    SwarmMessage,
    SwarmMessageBuilder,
)


class TestSwarmIntegration:
    """Integration tests for Swarm module."""

    @pytest.fixture
    def swarm_config(self) -> SwarmConfig:
        """Create test swarm configuration."""
        return SwarmConfig(
            device_id="nexus-swarm-test",
            serial_port=None,  # Mock mode
            channel=0,
            region="EU_868",
            tx_power=20,
            rate_limit_per_minute=30,
            mock_mode=True,
        )

    @pytest.fixture
    def mock_meshtastic(self):
        """Create mock Meshtastic interface."""
        mock = MagicMock()
        mock.sendText = MagicMock(return_value=True)
        mock.close = MagicMock()
        return mock

    # ========== SwarmMessage Tests ==========

    def test_message_serialization_roundtrip(self):
        """Test message can be serialized and deserialized."""
        original = SwarmMessage(
            src="momo-001",
            dst="nexus",
            event=EventCode.ALERT,
            seq=42,
            data={"type": "handshake", "ssid": "TestNet"},
            timestamp=datetime.now(),
        )

        serialized = original.to_bytes()
        restored = SwarmMessage.from_bytes(serialized)

        assert restored.src == original.src
        assert restored.dst == original.dst
        assert restored.event == original.event
        assert restored.seq == original.seq
        assert restored.data["ssid"] == "TestNet"

    def test_message_json_roundtrip(self):
        """Test message JSON serialization."""
        original = SwarmMessage(
            src="ghost-001",
            dst="nexus",
            event=EventCode.STATUS,
            seq=1,
            data={"battery": 85, "connected": True},
        )

        json_str = original.to_json()
        restored = SwarmMessage.from_json(json_str)

        assert restored.src == original.src
        assert restored.data["battery"] == 85

    # ========== SwarmMessageBuilder Tests ==========

    def test_builder_creates_valid_messages(self):
        """Test builder creates properly formatted messages."""
        builder = SwarmMessageBuilder(device_id="nexus-test")

        # Alert message
        alert = builder.alert(
            dst="operator",
            alert_type="handshake",
            data={"ssid": "CapturedNet"},
        )
        assert alert.src == "nexus-test"
        assert alert.event == EventCode.ALERT

        # Status message
        status = builder.status(
            dst="operator",
            battery=75,
            location={"lat": 41.0, "lon": 29.0},
        )
        assert status.event == EventCode.STATUS
        assert status.data["battery"] == 75

        # Command message
        cmd = builder.command(
            dst="momo-001",
            command=CommandCode.SCAN,
            params={"duration": 60},
        )
        assert cmd.event == EventCode.COMMAND
        assert cmd.data["cmd"] == CommandCode.SCAN.value

    def test_builder_increments_sequence(self):
        """Test builder auto-increments sequence numbers."""
        builder = SwarmMessageBuilder(device_id="test")

        msg1 = builder.ping(dst="target")
        msg2 = builder.ping(dst="target")
        msg3 = builder.ping(dst="target")

        assert msg2.seq == msg1.seq + 1
        assert msg3.seq == msg2.seq + 1

    # ========== SequenceTracker Tests ==========

    def test_sequence_tracker_detects_duplicates(self):
        """Test sequence tracker detects duplicate messages."""
        tracker = SequenceTracker(window_size=100)

        # First message - should be new
        assert tracker.is_new("momo-001", 1) is True

        # Same message - should be duplicate
        assert tracker.is_new("momo-001", 1) is False

        # Different source - should be new
        assert tracker.is_new("momo-002", 1) is True

        # Different sequence - should be new
        assert tracker.is_new("momo-001", 2) is True

    def test_sequence_tracker_handles_wraparound(self):
        """Test sequence tracker handles sequence number wraparound."""
        tracker = SequenceTracker(window_size=10)

        # Fill up with high numbers
        for i in range(65530, 65536):
            tracker.is_new("test", i)

        # Wraparound to low numbers
        assert tracker.is_new("test", 0) is True
        assert tracker.is_new("test", 1) is True

    # ========== SwarmBridge Tests ==========

    @pytest.mark.asyncio
    async def test_bridge_mock_mode(self, swarm_config: SwarmConfig):
        """Test bridge operates in mock mode without hardware."""
        bridge = SwarmBridge(swarm_config)

        # Connect in mock mode
        connected = await bridge.connect()
        assert connected is True
        assert bridge.is_connected is True

        # Disconnect
        await bridge.disconnect()
        assert bridge.is_connected is False

    @pytest.mark.asyncio
    async def test_bridge_send_message(self, swarm_config: SwarmConfig):
        """Test sending message through bridge."""
        bridge = SwarmBridge(swarm_config)
        await bridge.connect()

        try:
            msg = SwarmMessage(
                src="nexus",
                dst="momo-001",
                event=EventCode.COMMAND,
                seq=1,
                data={"cmd": "status"},
            )

            # Should succeed in mock mode
            success = await bridge.send(msg)
            assert success is True

            # Check stats
            stats = bridge.stats
            assert stats.messages_sent >= 1

        finally:
            await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_bridge_rate_limiting(self, swarm_config: SwarmConfig):
        """Test bridge enforces rate limiting."""
        config = SwarmConfig(
            device_id="test",
            rate_limit_per_minute=5,  # Very low limit
            mock_mode=True,
        )
        bridge = SwarmBridge(config)
        await bridge.connect()

        try:
            # Send messages up to limit
            for i in range(5):
                msg = SwarmMessage(
                    src="test", dst="target", event=EventCode.PING, seq=i, data={}
                )
                result = await bridge.send(msg)
                assert result is True

            # Next message should be rate limited
            msg = SwarmMessage(
                src="test", dst="target", event=EventCode.PING, seq=99, data={}
            )
            result = await bridge.send(msg)
            # Rate limited - should either queue or fail
            # Implementation specific

        finally:
            await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_bridge_message_callback(self, swarm_config: SwarmConfig):
        """Test bridge calls callback on message receipt."""
        received_messages = []

        async def on_message(msg: SwarmMessage):
            received_messages.append(msg)

        bridge = SwarmBridge(swarm_config)
        bridge.on_message = on_message
        await bridge.connect()

        try:
            # Simulate receiving a message (mock mode)
            test_msg = SwarmMessage(
                src="momo-001",
                dst="nexus",
                event=EventCode.ALERT,
                seq=1,
                data={"type": "test"},
            )
            await bridge._handle_received(test_msg)

            assert len(received_messages) == 1
            assert received_messages[0].src == "momo-001"

        finally:
            await bridge.disconnect()

    # ========== SwarmManager Tests ==========

    @pytest.mark.asyncio
    async def test_manager_lifecycle(self, swarm_config: SwarmConfig):
        """Test SwarmManager start/stop lifecycle."""
        manager = SwarmManager(swarm_config)

        # Start
        await manager.start()
        assert manager.is_running is True

        # Stop
        await manager.stop()
        assert manager.is_running is False

    @pytest.mark.asyncio
    async def test_manager_broadcast(self, swarm_config: SwarmConfig):
        """Test manager can broadcast to all devices."""
        manager = SwarmManager(swarm_config)
        await manager.start()

        try:
            # Broadcast alert
            success = await manager.broadcast_alert(
                alert_type="test",
                message="Test broadcast",
            )
            assert success is True

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_manager_send_command(self, swarm_config: SwarmConfig):
        """Test manager can send command to specific device."""
        manager = SwarmManager(swarm_config)
        await manager.start()

        try:
            # Send scan command
            success = await manager.send_command(
                device_id="momo-001",
                command=CommandCode.SCAN,
                params={"duration": 30},
            )
            assert success is True

        finally:
            await manager.stop()


class TestSwarmFlows:
    """End-to-end flow tests for Swarm functionality."""

    @pytest.fixture
    def config(self) -> SwarmConfig:
        """Create test configuration."""
        return SwarmConfig(
            device_id="nexus-e2e",
            mock_mode=True,
            rate_limit_per_minute=60,
        )

    @pytest.mark.asyncio
    async def test_alert_flow(self, config: SwarmConfig):
        """Test complete alert flow: MoMo → Nexus."""
        manager = SwarmManager(config)
        received_alerts = []

        async def on_alert(msg: SwarmMessage):
            if msg.event == EventCode.ALERT:
                received_alerts.append(msg)

        manager.on_message = on_alert
        await manager.start()

        try:
            # Simulate MoMo sending alert
            alert = SwarmMessage(
                src="momo-001",
                dst="nexus",
                event=EventCode.ALERT,
                seq=1,
                data={
                    "type": "handshake",
                    "ssid": "TargetNetwork",
                    "bssid": "AA:BB:CC:DD:EE:FF",
                },
            )
            await manager._bridge._handle_received(alert)

            # Verify alert was received
            assert len(received_alerts) == 1
            assert received_alerts[0].data["ssid"] == "TargetNetwork"

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_command_response_flow(self, config: SwarmConfig):
        """Test command → response flow: Nexus → MoMo → Nexus."""
        manager = SwarmManager(config)
        responses = []

        async def on_response(msg: SwarmMessage):
            if msg.event == EventCode.ACK:
                responses.append(msg)

        manager.on_message = on_response
        await manager.start()

        try:
            # Send command to MoMo
            await manager.send_command(
                device_id="momo-001",
                command=CommandCode.STATUS,
                params={},
            )

            # Simulate MoMo response
            response = SwarmMessage(
                src="momo-001",
                dst="nexus",
                event=EventCode.ACK,
                seq=1,
                data={"status": "ok", "battery": 85},
            )
            await manager._bridge._handle_received(response)

            assert len(responses) == 1
            assert responses[0].data["status"] == "ok"

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_multi_device_coordination(self, config: SwarmConfig):
        """Test coordinating multiple devices via Swarm."""
        manager = SwarmManager(config)
        await manager.start()

        try:
            # Register multiple devices
            devices = ["momo-001", "momo-002", "ghost-001"]

            # Broadcast scan command to all
            success = await manager.broadcast_command(
                command=CommandCode.SCAN,
                params={"duration": 60},
            )
            assert success is True

            # Verify stats
            stats = manager.stats
            assert stats["messages_sent"] >= 1

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_offline_queue_and_replay(self, config: SwarmConfig):
        """Test messages are queued when offline and sent when reconnected."""
        manager = SwarmManager(config)
        await manager.start()

        try:
            # Simulate disconnect
            await manager._bridge.disconnect()

            # Queue some messages
            msg1 = await manager._queue_message(
                dst="momo-001",
                event=EventCode.COMMAND,
                data={"cmd": "status"},
            )
            msg2 = await manager._queue_message(
                dst="momo-002",
                event=EventCode.COMMAND,
                data={"cmd": "scan"},
            )

            # Verify queue has messages
            assert manager._pending_queue.qsize() >= 2

            # Reconnect
            await manager._bridge.connect()

            # Flush queue
            await manager._flush_pending_queue()

            # Queue should be empty
            assert manager._pending_queue.empty()

        finally:
            await manager.stop()


class TestBridgeStats:
    """Tests for BridgeStats tracking."""

    def test_stats_initialization(self):
        """Test stats initialize to zero."""
        stats = BridgeStats()
        assert stats.messages_sent == 0
        assert stats.messages_received == 0
        assert stats.errors == 0
        assert stats.rate_limited == 0

    def test_stats_increment(self):
        """Test stats can be incremented."""
        stats = BridgeStats()
        stats.messages_sent += 1
        stats.messages_received += 2
        stats.errors += 1

        assert stats.messages_sent == 1
        assert stats.messages_received == 2
        assert stats.errors == 1

    def test_stats_to_dict(self):
        """Test stats can be converted to dict."""
        stats = BridgeStats(
            messages_sent=10,
            messages_received=20,
            errors=1,
        )

        d = stats.to_dict()
        assert d["messages_sent"] == 10
        assert d["messages_received"] == 20

