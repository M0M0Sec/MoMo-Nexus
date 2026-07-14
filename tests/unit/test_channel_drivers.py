"""
Tests for channel drivers.
"""

import asyncio

import pytest

from nexus.channels.ble import BLEAK_AVAILABLE, BLEChannel
from nexus.channels.cellular import SERIAL_AVAILABLE, CellularChannel
from nexus.channels.lora import MESHTASTIC_AVAILABLE, LoRaChannel
from nexus.channels.wifi import AIOHTTP_AVAILABLE, WiFiChannel
from nexus.domain.enums import ChannelStatus, ChannelType
from nexus.domain.models import Message


class TestLoRaChannel:
    """Tests for LoRaChannel."""

    def test_create_channel(self) -> None:
        """Test creating LoRa channel."""
        channel = LoRaChannel(
            serial_port="/dev/ttyUSB0",
            channel_name="Test",
        )
        assert channel.channel_type == ChannelType.LORA
        assert channel.name == "lora"
        assert channel._serial_port == "/dev/ttyUSB0"

    def test_constraints(self) -> None:
        """Test LoRa constraints."""
        assert LoRaChannel.MAX_PAYLOAD_SIZE == 200
        assert LoRaChannel.DUTY_CYCLE_LIMIT == 0.01

    @pytest.mark.skipif(not MESHTASTIC_AVAILABLE, reason="Meshtastic not installed")
    @pytest.mark.asyncio
    async def test_connect_without_device(self) -> None:
        """Test connection fails gracefully without device."""
        channel = LoRaChannel(serial_port="/dev/nonexistent")

        with pytest.raises(Exception):
            await channel.connect()

    def test_serialize_message(self) -> None:
        """Test message serialization for LoRa."""
        channel = LoRaChannel()
        msg = Message(
            src="momo-001",
            type="status",
            data={"battery": 85},
        )

        payload = channel._serialize_message(msg)

        assert isinstance(payload, bytes)
        assert len(payload) < LoRaChannel.MAX_PAYLOAD_SIZE
        assert b"momo-001" in payload

    def test_serialize_preserves_full_message_id(self) -> None:
        """Roadmap 2.9: the full message ID must survive the wire (was truncated to 8
        chars, breaking ACK correlation and raising collision odds)."""
        channel = LoRaChannel()
        msg = Message(src="momo-001", type="status", data={"battery": 85})
        assert len(msg.id) == 12  # generate_id → uuid4().hex[:12]

        restored = channel._deserialize_message(
            channel._serialize_message(msg), sender="momo-001"
        )
        assert restored.id == msg.id  # full ID, not truncated


class TestCellularChannel:
    """Tests for CellularChannel."""

    def test_create_channel(self) -> None:
        """Test creating cellular channel."""
        channel = CellularChannel(
            serial_port="/dev/ttyUSB2",
            apn="internet",
            api_endpoint="https://api.example.com/messages",
        )
        assert channel.channel_type == ChannelType.CELLULAR
        assert channel.name == "cellular"
        assert channel._apn == "internet"

    def test_default_baud_rate(self) -> None:
        """Test default baud rate."""
        channel = CellularChannel()
        assert channel._baud_rate == 115200

    @pytest.mark.skipif(not SERIAL_AVAILABLE, reason="pyserial not installed")
    @pytest.mark.asyncio
    async def test_connect_without_device(self) -> None:
        """Test connection fails gracefully without device."""
        from nexus.channels.base import ChannelStatus

        channel = CellularChannel(serial_port="/dev/nonexistent")

        # Connection should fail gracefully (not raise)
        await channel.connect()

        # Channel should be in DOWN or DEGRADED state
        assert channel.status in (ChannelStatus.DOWN, ChannelStatus.DEGRADED)
        assert not channel.is_connected

    def test_modem_states(self) -> None:
        """Test modem state tracking."""
        from nexus.channels.cellular import ModemState

        channel = CellularChannel()
        assert channel.modem_state == ModemState.DISCONNECTED


class TestWiFiChannel:
    """Tests for WiFiChannel."""

    def test_create_channel(self) -> None:
        """Test creating WiFi channel."""
        channel = WiFiChannel(
            ssid="TestNetwork",
            password="password123",
            api_endpoint="http://192.168.1.100:8080/api",
        )
        assert channel.channel_type == ChannelType.WIFI
        assert channel.name == "wifi"
        assert channel._ssid == "TestNetwork"

    def test_wifi_modes(self) -> None:
        """Test WiFi modes."""
        from nexus.channels.wifi import WiFiMode

        client = WiFiChannel(mode=WiFiMode.CLIENT)
        assert client.mode == WiFiMode.CLIENT

        ap = WiFiChannel(mode=WiFiMode.AP)
        assert ap.mode == WiFiMode.AP

    @pytest.mark.asyncio
    async def test_disconnect_cancels_receive_task(self) -> None:
        """Roadmap 3.5: the WebSocket receive loop must be tracked and cancelled on
        disconnect (was a dangling create_task that reconnects kept multiplying)."""
        channel = WiFiChannel()

        async def _sleeper():
            await asyncio.sleep(3600)

        channel._ws_receive_task = asyncio.create_task(_sleeper())
        task = channel._ws_receive_task

        await channel._disconnect()
        await asyncio.sleep(0)  # let the cancellation propagate

        assert task.cancelled()
        assert channel._ws_receive_task is None

    def test_peer_registration(self) -> None:
        """Test peer registration."""
        channel = WiFiChannel()

        channel.register_peer("momo-001", "192.168.1.50:8765")
        assert "momo-001" in channel.peers
        assert channel.peers["momo-001"] == "192.168.1.50:8765"

        channel.unregister_peer("momo-001")
        assert "momo-001" not in channel.peers


class TestBLEChannel:
    """Tests for BLEChannel."""

    def test_create_channel(self) -> None:
        """Test creating BLE channel."""
        channel = BLEChannel(
            adapter="hci0",
            auto_connect=True,
        )
        assert channel.channel_type == ChannelType.BLE
        assert channel.name == "ble"
        assert channel._adapter == "hci0"

    def test_max_payload_size(self) -> None:
        """Test BLE payload constraints."""
        assert BLEChannel.MAX_PAYLOAD_SIZE == 512

    def test_discovered_devices(self) -> None:
        """Test discovered devices property."""
        channel = BLEChannel()
        assert channel.discovered_devices == {}
        assert channel.connected_devices == []

    @pytest.mark.asyncio
    async def test_rx_buffer_overflow_discarded(self) -> None:
        """Roadmap 3.4: a delimiter-less stream must not grow the buffer without bound."""
        channel = BLEChannel()
        await channel._handle_notification("AA:BB", b"x" * (BLEChannel.MAX_RX_BUFFER + 10))
        assert channel._rx_buffer["AA:BB"] == b""  # overflowed → discarded

    @pytest.mark.asyncio
    async def test_disconnect_clears_rx_buffer(self) -> None:
        """Roadmap 3.4: disconnecting a device must free its reassembly buffer."""
        channel = BLEChannel()
        channel._rx_buffer["AA:BB"] = b"partial-data"

        class _FakeClient:
            is_connected = False

        channel._connections["AA:BB"] = _FakeClient()
        await channel.disconnect_device("AA:BB")
        assert "AA:BB" not in channel._rx_buffer

    @pytest.mark.skipif(not BLEAK_AVAILABLE, reason="bleak not installed")
    @pytest.mark.asyncio
    async def test_scan_without_adapter(self) -> None:
        """Test scan works without adapter."""
        channel = BLEChannel()
        # Should not raise, just return empty list
        devices = await channel.scan(timeout=1.0)
        assert isinstance(devices, list)


class TestChannelAvailability:
    """Test channel library availability flags."""

    def test_meshtastic_flag(self) -> None:
        """Test Meshtastic availability flag."""
        assert isinstance(MESHTASTIC_AVAILABLE, bool)

    def test_serial_flag(self) -> None:
        """Test pyserial availability flag."""
        assert isinstance(SERIAL_AVAILABLE, bool)

    def test_aiohttp_flag(self) -> None:
        """Test aiohttp availability flag."""
        assert isinstance(AIOHTTP_AVAILABLE, bool)

    def test_bleak_flag(self) -> None:
        """Test bleak availability flag."""
        assert isinstance(BLEAK_AVAILABLE, bool)

