"""
Unit tests for Swarm integration.

Tests the Swarm protocol, bridge, and manager components.
"""

import asyncio
import json
import time

import pytest

from nexus.swarm.bridge import BridgeStats, SwarmBridge, SwarmConfig
from nexus.swarm.protocol import (
    MAX_SWARM_MESSAGE_SIZE,
    AckStatus,
    CommandCode,
    EventCode,
    SequenceTracker,
    SwarmMessage,
    SwarmMessageBuilder,
    SwarmMessageType,
)


class TestSwarmMessage:
    """Tests for SwarmMessage class."""

    def test_create_message(self):
        """Test basic message creation."""
        msg = SwarmMessage(
            type=SwarmMessageType.ALERT,
            source="momo-001",
            data={"evt": "hs_cap", "ssid": "TestWiFi"},
        )

        assert msg.type == SwarmMessageType.ALERT
        assert msg.source == "momo-001"
        assert msg.data["evt"] == "hs_cap"
        assert msg.version == 1

    def test_to_json_compact(self):
        """Test compact JSON serialization."""
        msg = SwarmMessage(
            type=SwarmMessageType.ALERT,
            source="momo-001",
            data={"evt": "hs_cap"},
            timestamp=1700000000,
            sequence=42,
        )

        json_str = msg.to_json(compact=True)

        # Should not have spaces
        assert " " not in json_str
        assert '"v":1' in json_str
        assert '"t":"alert"' in json_str
        assert '"src":"momo-001"' in json_str

    def test_to_json_with_destination(self):
        """Test JSON with destination field."""
        msg = SwarmMessage(
            type=SwarmMessageType.CMD,
            source="nexus-hub",
            destination="momo-001",
            data={"cmd": "status"},
            timestamp=1700000000,
            sequence=1,
        )

        json_str = msg.to_json()
        data = json.loads(json_str)

        assert data["dst"] == "momo-001"

    def test_from_json_valid(self):
        """Test parsing valid JSON."""
        json_str = '{"v":1,"t":"alert","src":"momo-001","ts":1700000000,"seq":42,"d":{"evt":"hs_cap"}}'

        msg = SwarmMessage.from_json(json_str)

        assert msg is not None
        assert msg.type == SwarmMessageType.ALERT
        assert msg.source == "momo-001"
        assert msg.sequence == 42
        assert msg.data["evt"] == "hs_cap"

    def test_from_json_invalid_version(self):
        """Test parsing with wrong version."""
        json_str = '{"v":99,"t":"alert","src":"momo-001","ts":1700000000,"seq":42,"d":{}}'

        msg = SwarmMessage.from_json(json_str)

        assert msg is None

    def test_from_json_missing_fields(self):
        """Test parsing with missing required fields."""
        json_str = '{"v":1,"t":"alert"}'  # Missing src, ts, seq, d

        msg = SwarmMessage.from_json(json_str)

        assert msg is None

    def test_from_json_invalid_json(self):
        """Test parsing invalid JSON."""
        msg = SwarmMessage.from_json("not json at all")

        assert msg is None

    def test_from_json_unknown_type_rejected(self):
        """Roadmap 2.4: an unknown message type must be rejected (None), not stored as a
        raw string that would later crash `.type.value` on the receive path."""
        json_str = '{"v":1,"t":"bogus","src":"momo-001","ts":1700000000,"seq":1,"d":{}}'
        msg = SwarmMessage.from_json(json_str)
        assert msg is None

    def test_to_dict_from_dict_roundtrip(self):
        """Roadmap 2.8: to_dict/from_dict round-trip preserves the message."""
        msg = SwarmMessage(
            version=1, type=SwarmMessageType.ALERT, source="hub",
            timestamp=1700000000, sequence=7, data={"evt": "hs_cap"},
        )
        d = msg.to_dict()
        assert isinstance(d, dict)
        back = SwarmMessage.from_dict(d)
        assert back is not None
        assert back.type == SwarmMessageType.ALERT
        assert back.sequence == 7
        assert back.data == {"evt": "hs_cap"}

    def test_embedding_dict_avoids_double_encoding(self):
        """Roadmap 2.8: embedding via to_dict must not double-encode (escaped strings)."""
        msg = SwarmMessage(
            version=1, type=SwarmMessageType.ALERT, source="hub",
            timestamp=1700000000, sequence=1, data={"msg": "hello world"},
        )
        dict_size = len(json.dumps({"swarm": msg.to_dict()}))
        string_size = len(json.dumps({"swarm": msg.to_json(compact=True)}))
        assert dict_size < string_size  # no escaped-quote bloat

    def test_to_bytes_and_back(self):
        """Test bytes serialization round-trip."""
        original = SwarmMessage(
            type=SwarmMessageType.STATUS,
            source="momo-002",
            data={"up": 3600, "bat": 85},
            timestamp=1700000000,
            sequence=100,
        )

        bytes_data = original.to_bytes()
        recovered = SwarmMessage.from_bytes(bytes_data)

        assert recovered is not None
        assert recovered.type == original.type
        assert recovered.source == original.source
        assert recovered.data == original.data

    def test_size_calculation(self):
        """Test message size calculation."""
        msg = SwarmMessage(
            type=SwarmMessageType.ALERT,
            source="momo-001",
            data={"evt": "test"},
            timestamp=1700000000,
            sequence=1,
        )

        size = msg.size()

        assert size == len(msg.to_bytes())
        assert size < MAX_SWARM_MESSAGE_SIZE

    def test_is_valid_size_small(self):
        """Test size validation for small message."""
        msg = SwarmMessage(
            type=SwarmMessageType.ACK,
            source="x",
            data={"ref": 1, "status": "ok"},
            timestamp=1700000000,
            sequence=1,
        )

        assert msg.is_valid_size() is True

    def test_is_valid_size_large(self):
        """Test size validation for oversized message."""
        # Create message with large data
        large_data = {"x": "A" * 300}  # Definitely over 237 bytes

        msg = SwarmMessage(
            type=SwarmMessageType.DATA,
            source="momo-001",
            data=large_data,
            timestamp=1700000000,
            sequence=1,
        )

        assert msg.is_valid_size() is False


class TestSwarmMessageBuilder:
    """Tests for SwarmMessageBuilder class."""

    def test_builder_init(self):
        """Test builder initialization."""
        builder = SwarmMessageBuilder("momo-001")

        assert builder.device_id == "momo-001"

    def test_build_alert(self):
        """Test building alert message."""
        builder = SwarmMessageBuilder("momo-001")

        msg = builder.alert(
            EventCode.HANDSHAKE_CAPTURED,
            {"ssid": "TestWiFi", "bssid": "AA:BB:CC:DD:EE:FF"},
        )

        assert msg.type == SwarmMessageType.ALERT
        assert msg.source == "momo-001"
        assert msg.data["evt"] == "hs_cap"
        assert msg.data["ssid"] == "TestWiFi"

    def test_build_status(self):
        """Test building status message."""
        builder = SwarmMessageBuilder("momo-001")

        msg = builder.status(
            uptime=3600,
            battery=85,
            temperature=45,
            gps=(41.015, 28.979),
            aps_seen=25,
            handshakes=3,
        )

        assert msg.type == SwarmMessageType.STATUS
        assert msg.data["up"] == 3600
        assert msg.data["bat"] == 85
        assert msg.data["temp"] == 45
        assert msg.data["gps"] == [41.015, 28.979]

    def test_build_command(self):
        """Test building command message."""
        builder = SwarmMessageBuilder("nexus-hub")

        msg = builder.command(
            CommandCode.DEAUTH,
            {"bssid": "AA:BB:CC:DD:EE:FF", "count": 10},
            "momo-001",
        )

        assert msg.type == SwarmMessageType.CMD
        assert msg.destination == "momo-001"
        assert msg.data["cmd"] == "deauth"
        assert msg.data["bssid"] == "AA:BB:CC:DD:EE:FF"

    def test_build_ack_success(self):
        """Test building success ack message."""
        builder = SwarmMessageBuilder("momo-001")

        msg = builder.ack(
            ref_seq=42,
            status=AckStatus.OK,
            destination="nexus-hub",
            result="Command executed",
        )

        assert msg.type == SwarmMessageType.ACK
        assert msg.data["ref"] == 42
        assert msg.data["status"] == "ok"
        assert msg.data["result"] == "Command executed"

    def test_build_ack_error(self):
        """Test building error ack message."""
        builder = SwarmMessageBuilder("momo-001")

        msg = builder.ack(
            ref_seq=42,
            status=AckStatus.ERROR,
            destination="nexus-hub",
            error="Device busy",
        )

        assert msg.data["status"] == "error"
        assert msg.data["error"] == "Device busy"

    def test_build_gps(self):
        """Test building GPS message."""
        builder = SwarmMessageBuilder("momo-001")

        msg = builder.gps(
            lat=41.015137,
            lon=28.979530,
            alt=150,
            speed=1.5,
            sats=8,
        )

        assert msg.type == SwarmMessageType.GPS
        assert msg.data["lat"] == 41.015137
        assert msg.data["lon"] == 28.97953
        assert msg.data["sats"] == 8

    def test_sequence_increment(self):
        """Test sequence number auto-increment."""
        builder = SwarmMessageBuilder("momo-001")

        msg1 = builder.alert(EventCode.NEW_AP, {"ssid": "AP1"})
        msg2 = builder.alert(EventCode.NEW_AP, {"ssid": "AP2"})
        msg3 = builder.alert(EventCode.NEW_AP, {"ssid": "AP3"})

        assert msg1.sequence == 1
        assert msg2.sequence == 2
        assert msg3.sequence == 3

    def test_data_chunk(self):
        """Test building data chunk message."""
        builder = SwarmMessageBuilder("momo-001")

        msg = builder.data_chunk(
            chunk_id="abc123",
            name="handshake.pcap",
            chunk_num=1,
            total_chunks=3,
            data="SGVsbG8gV29ybGQ=",  # Base64
            destination="nexus-hub",
        )

        assert msg.type == SwarmMessageType.DATA
        assert msg.data["id"] == "abc123"
        assert msg.data["chunk"] == 1
        assert msg.data["total"] == 3


class TestSequenceTracker:
    """Tests for SequenceTracker class."""

    def test_source_cap_evicts_oldest(self):
        """Roadmap Faz 5: distinct source IDs are bounded (LRU) to resist spoofed
        source IDs inflating memory without bound."""
        tracker = SequenceTracker(window_size=10, max_sources=3)
        for i in range(3):
            assert tracker.is_valid(f"dev-{i}", 1) is True
        assert len(tracker._seen) == 3

        tracker.is_valid("dev-3", 1)  # 4th source → evict LRU (dev-0)
        assert len(tracker._seen) == 3
        assert "dev-0" not in tracker._seen
        assert "dev-0" not in tracker._last_seq
        assert "dev-3" in tracker._seen

    def test_valid_sequence_first(self):
        """Test first sequence from new source."""
        tracker = SequenceTracker()

        assert tracker.is_valid("momo-001", 1) is True

    def test_valid_sequence_increment(self):
        """Test incrementing sequence."""
        tracker = SequenceTracker()

        assert tracker.is_valid("momo-001", 1) is True
        assert tracker.is_valid("momo-001", 2) is True
        assert tracker.is_valid("momo-001", 3) is True

    def test_replay_detection(self):
        """Test replay attack detection."""
        tracker = SequenceTracker()

        assert tracker.is_valid("momo-001", 5) is True
        assert tracker.is_valid("momo-001", 5) is False  # Replay!

    def test_old_sequence_beyond_window_rejected(self):
        """A sequence older than the window is rejected (can't tell from a replay)."""
        tracker = SequenceTracker(window_size=100)

        assert tracker.is_valid("momo-001", 500) is True
        assert tracker.is_valid("momo-001", 300) is False  # 200 behind > window(100)

    def test_out_of_order_within_window_accepted(self):
        """Roadmap 2.2: legitimate out-of-order delivery within the window is accepted
        (the old code rejected ALL sequence <= last, losing messages)."""
        tracker = SequenceTracker(window_size=100)

        assert tracker.is_valid("momo-001", 10) is True
        assert tracker.is_valid("momo-001", 8) is True   # out-of-order, within window
        assert tracker.is_valid("momo-001", 9) is True   # out-of-order, within window
        assert tracker.is_valid("momo-001", 8) is False  # now a replay
        assert tracker.is_valid("momo-001", 11) is True  # forward again

    def test_wraparound(self):
        """Test sequence wraparound handling."""
        tracker = SequenceTracker()

        # Simulate high sequence
        assert tracker.is_valid("momo-001", 65530) is True

        # Wraparound to low sequence should be valid
        assert tracker.is_valid("momo-001", 5) is True

    def test_multiple_sources(self):
        """Test tracking multiple sources independently."""
        tracker = SequenceTracker()

        assert tracker.is_valid("momo-001", 100) is True
        assert tracker.is_valid("momo-002", 50) is True
        assert tracker.is_valid("momo-001", 101) is True
        assert tracker.is_valid("momo-002", 51) is True

    def test_reset_specific(self):
        """Test resetting specific source."""
        tracker = SequenceTracker()

        tracker.is_valid("momo-001", 100)
        tracker.is_valid("momo-002", 50)

        tracker.reset("momo-001")

        # momo-001 should accept any sequence now
        assert tracker.is_valid("momo-001", 1) is True

        # momo-002 should still track
        assert tracker.is_valid("momo-002", 50) is False

    def test_reset_all(self):
        """Test resetting all sources."""
        tracker = SequenceTracker()

        tracker.is_valid("momo-001", 100)
        tracker.is_valid("momo-002", 50)

        tracker.reset()

        # Both should accept any sequence
        assert tracker.is_valid("momo-001", 1) is True
        assert tracker.is_valid("momo-002", 1) is True

    def test_get_stats(self):
        """Test statistics retrieval."""
        tracker = SequenceTracker()

        tracker.is_valid("momo-001", 1)
        tracker.is_valid("momo-001", 2)
        tracker.is_valid("momo-002", 1)

        stats = tracker.get_stats()

        assert stats["tracked_sources"] == 2
        assert "momo-001" in stats["sources"]
        assert "momo-002" in stats["sources"]


class TestBridgeStats:
    """Tests for BridgeStats class."""

    def test_default_values(self):
        """Test default statistics values."""
        stats = BridgeStats()

        assert stats.messages_sent == 0
        assert stats.messages_received == 0
        assert stats.errors == 0

    def test_uptime(self):
        """Test uptime calculation."""
        stats = BridgeStats()
        stats.start_time = time.time() - 100  # 100 seconds ago

        uptime = stats.uptime

        assert 99 <= uptime <= 101

    def test_to_dict(self):
        """Test dictionary conversion."""
        stats = BridgeStats()
        stats.messages_sent = 10
        stats.messages_received = 5

        d = stats.to_dict()

        assert d["messages_sent"] == 10
        assert d["messages_received"] == 5
        assert "uptime" in d


class TestSwarmConfig:
    """Tests for SwarmConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SwarmConfig()

        assert config.enabled is True
        assert config.device_id == "nexus-hub"
        assert config.heartbeat_interval == 300
        assert config.alerts_per_minute == 10

    def test_custom_config(self):
        """Test custom configuration."""
        config = SwarmConfig(
            enabled=False,
            device_id="custom-hub",
            heartbeat_interval=60,
        )

        assert config.enabled is False
        assert config.device_id == "custom-hub"
        assert config.heartbeat_interval == 60


class TestSwarmBridge:
    """Tests for SwarmBridge class."""

    def test_bridge_init(self):
        """Test bridge initialization."""
        bridge = SwarmBridge()

        assert bridge.config is not None
        assert bridge.stats is not None
        assert bridge.is_running is False

    def test_bridge_with_config(self):
        """Test bridge with custom config."""
        config = SwarmConfig(device_id="test-hub")
        bridge = SwarmBridge(config=config)

        assert bridge.config.device_id == "test-hub"
        assert bridge.builder.device_id == "test-hub"

    def test_rate_limit(self):
        """Test rate limiting."""
        config = SwarmConfig(alerts_per_minute=3)
        bridge = SwarmBridge(config=config)

        # First 3 should pass
        assert bridge._check_rate_limit() is True
        assert bridge._check_rate_limit() is True
        assert bridge._check_rate_limit() is True

        # 4th should fail
        assert bridge._check_rate_limit() is False

    def test_register_command_handler(self):
        """Test command handler registration."""
        bridge = SwarmBridge()

        async def my_handler(params):
            return {"result": "ok"}

        bridge.register_command(CommandCode.STATUS, my_handler)

        assert "status" in bridge._command_handlers

    def test_on_event_callback(self):
        """Test event callback registration."""
        bridge = SwarmBridge()

        async def my_callback(event, data):
            pass

        bridge.on_event(my_callback)

        assert len(bridge._event_callbacks) == 1

    @pytest.mark.asyncio
    async def test_stop_sends_shutdown_notification(self):
        """Roadmap 2.6: stop() must actually send SHUTDOWN. Previously _running was set
        False before send_alert(), and the guarded send path dropped the message."""
        sent = []

        class FakeLora:
            async def send(self, nexus_msg):
                sent.append(nexus_msg)
                return True

        bridge = SwarmBridge(lora_channel=FakeLora(), config=SwarmConfig(device_id="hub"))
        bridge._running = True

        await bridge.stop()

        assert bridge.is_running is False
        assert len(sent) == 1  # shutdown actually transmitted
        # Embedded as a dict now (2.8, no double-encoding); serialize to check the text.
        assert "Nexus Swarm offline" in json.dumps(sent[0].data["swarm"])

    def test_devices_tracking_is_bounded(self):
        """Roadmap Faz 5: tracked devices are LRU-bounded (source IDs are untrusted)."""
        bridge = SwarmBridge(config=SwarmConfig(device_id="hub"))
        bridge._max_tracked_devices = 3
        msg = SwarmMessage(
            version=1, type=SwarmMessageType.ALERT, source="x",
            timestamp=0, sequence=1, data={},
        )
        for i in range(5):
            bridge._update_device(f"dev-{i}", msg)
        assert len(bridge._devices) == 3
        assert "dev-0" not in bridge._devices  # evicted
        assert "dev-4" in bridge._devices

    @pytest.mark.asyncio
    async def test_send_alert_tracks_task(self):
        """Roadmap 2.5: fire-and-forget sends must be tracked (not GC-able) and run."""
        sent = []

        class FakeLora:
            async def send(self, nexus_msg):
                sent.append(nexus_msg)
                return True

        bridge = SwarmBridge(lora_channel=FakeLora(), config=SwarmConfig(device_id="hub"))
        bridge._running = True

        ok = bridge.send_alert(EventCode.STARTUP, {"msg": "hi"})
        assert ok is True
        assert len(bridge._send_tasks) == 1  # tracked, not dangling

        # Let the tracked send task run to completion.
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(sent) == 1
        assert len(bridge._send_tasks) == 0  # cleaned up by the done callback


class TestEventCodes:
    """Tests for EventCode enum."""

    def test_wifi_events(self):
        """Test WiFi event codes."""
        assert EventCode.HANDSHAKE_CAPTURED.value == "hs_cap"
        assert EventCode.PMKID_CAPTURED.value == "pmkid"
        assert EventCode.NEW_AP.value == "new_ap"

    def test_attack_events(self):
        """Test attack event codes."""
        assert EventCode.EVIL_TWIN_CONNECT.value == "et_conn"
        assert EventCode.KARMA_CLIENT.value == "karma"

    def test_system_events(self):
        """Test system event codes."""
        assert EventCode.STARTUP.value == "startup"
        assert EventCode.SHUTDOWN.value == "shutdown"

    def test_ghost_events(self):
        """Test GhostBridge event codes."""
        assert EventCode.GHOST_BEACON.value == "gh_beacon"
        assert EventCode.GHOST_TUNNEL.value == "gh_tunnel"

    def test_mimic_events(self):
        """Test Mimic event codes."""
        assert EventCode.MIMIC_TRIGGER.value == "mm_trig"
        assert EventCode.MIMIC_INJECT.value == "mm_inject"


class TestCommandCodes:
    """Tests for CommandCode enum."""

    def test_general_commands(self):
        """Test general command codes."""
        assert CommandCode.STATUS.value == "status"
        assert CommandCode.PING.value == "ping"
        assert CommandCode.SHELL.value == "shell"

    def test_momo_commands(self):
        """Test MoMo-specific commands."""
        assert CommandCode.DEAUTH.value == "deauth"
        assert CommandCode.EVIL_TWIN.value == "eviltwin"
        assert CommandCode.CAPTURE.value == "capture"

    def test_ghost_commands(self):
        """Test GhostBridge commands."""
        assert CommandCode.GHOST_START.value == "gh_start"
        assert CommandCode.GHOST_STOP.value == "gh_stop"

    def test_mimic_commands(self):
        """Test Mimic commands."""
        assert CommandCode.MIMIC_ARM.value == "mm_arm"
        assert CommandCode.MIMIC_DISARM.value == "mm_disarm"

