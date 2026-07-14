"""
Tests for domain models.
"""

from datetime import datetime

import pytest

from nexus.domain.enums import (
    ChannelType,
    DeviceStatus,
    DeviceType,
    MessageType,
    Priority,
)
from nexus.domain.models import (
    Channel,
    ChannelMetrics,
    Command,
    CommandResult,
    Device,
    GPSLocation,
    Message,
    RoutingResult,
)


class TestMessage:
    """Tests for Message model."""

    def test_create_message(self) -> None:
        """Test basic message creation."""
        msg = Message(
            src="momo-001",
            type=MessageType.STATUS,
        )
        assert msg.src == "momo-001"
        assert msg.type == MessageType.STATUS
        assert msg.id is not None
        assert len(msg.id) == 12
        assert msg.pri == Priority.NORMAL
        assert msg.dst is None

    def test_message_with_destination(self) -> None:
        """Test message with destination."""
        msg = Message(
            src="momo-001",
            dst="nexus",
            type=MessageType.ALERT,
            pri=Priority.HIGH,
        )
        assert msg.dst == "nexus"
        assert msg.pri == Priority.HIGH

    def test_message_with_data(self) -> None:
        """Test message with payload data."""
        data = {"battery": 85, "status": "ok"}
        msg = Message(
            src="momo-001",
            type=MessageType.STATUS,
            data=data,
        )
        assert msg.data == data
        assert msg.data["battery"] == 85

    def test_message_needs_ack(self) -> None:
        """Test ACK requirement."""
        msg = Message(
            src="momo-001",
            type=MessageType.COMMAND,
            ack_required=True,
        )
        assert msg.needs_ack() is True

        # ACK messages don't need ACK
        ack = Message(
            src="momo-001",
            type=MessageType.ACK,
            ack_required=True,
        )
        assert ack.needs_ack() is False

    def test_create_ack(self) -> None:
        """Test creating ACK response."""
        msg = Message(
            src="momo-001",
            dst="nexus",
            type=MessageType.COMMAND,
            pri=Priority.HIGH,
        )
        ack = msg.create_ack(success=True)

        assert ack.type == MessageType.ACK
        assert ack.ack_id == msg.id
        assert ack.dst == msg.src
        assert ack.src == "nexus"

    def test_create_nack(self) -> None:
        """Test creating NACK response."""
        msg = Message(src="momo-001", type=MessageType.COMMAND)
        nack = msg.create_ack(success=False)
        assert nack.type == MessageType.NACK


class TestDevice:
    """Tests for Device model."""

    def test_create_device(self) -> None:
        """Test basic device creation."""
        device = Device(id="momo-001", type=DeviceType.MOMO)
        assert device.id == "momo-001"
        assert device.type == DeviceType.MOMO
        assert device.status == DeviceStatus.UNREGISTERED

    def test_device_with_location(self) -> None:
        """Test device with GPS location."""
        loc = GPSLocation(lat=41.0082, lon=28.9784, alt=100)
        device = Device(
            id="momo-001",
            type=DeviceType.MOMO,
            location=loc,
        )
        assert device.location is not None
        assert device.location.lat == 41.0082
        assert device.location.to_tuple() == (41.0082, 28.9784)

    def test_device_is_online(self) -> None:
        """Test online check."""
        device = Device(id="momo-001", status=DeviceStatus.ONLINE)
        assert device.is_online() is True

        device.status = DeviceStatus.OFFLINE
        assert device.is_online() is False

    def test_device_is_reachable(self) -> None:
        """Test reachable check."""
        device = Device(id="momo-001", status=DeviceStatus.ONLINE)
        assert device.is_reachable() is True

        device.status = DeviceStatus.SLEEPING
        assert device.is_reachable() is True

        device.status = DeviceStatus.OFFLINE
        assert device.is_reachable() is False


class TestChannel:
    """Tests for Channel model."""

    def test_create_channel(self) -> None:
        """Test channel creation."""
        channel = Channel(name="lora-1", type=ChannelType.LORA)
        assert channel.name == "lora-1"
        assert channel.type == ChannelType.LORA
        assert channel.enabled is True

    def test_channel_score_normal(self) -> None:
        """Test channel scoring for normal priority."""
        channel = Channel(
            name="test",
            type=ChannelType.WIFI,
            metrics=ChannelMetrics(latency_ms=100),
        )
        channel.status = "up"

        score = channel.score(Priority.NORMAL)
        assert score > 0

    def test_channel_score_unavailable(self) -> None:
        """Test unavailable channel has infinite score."""
        channel = Channel(name="test", type=ChannelType.WIFI, enabled=False)
        score = channel.score()
        assert score == float("inf")


class TestGPSLocation:
    """Tests for GPSLocation model."""

    def test_valid_coordinates(self) -> None:
        """Test valid GPS coordinates."""
        loc = GPSLocation(lat=41.0082, lon=28.9784)
        assert loc.lat == 41.0082
        assert loc.lon == 28.9784

    def test_invalid_latitude(self) -> None:
        """Test invalid latitude."""
        with pytest.raises(ValueError):
            GPSLocation(lat=91.0, lon=0)

    def test_invalid_longitude(self) -> None:
        """Test invalid longitude."""
        with pytest.raises(ValueError):
            GPSLocation(lat=0, lon=181)


class TestCommand:
    """Tests for Command model."""

    def test_create_command(self) -> None:
        """Test command creation."""
        cmd = Command(
            device_id="momo-001",
            cmd="deauth",
            params={"target": "aa:bb:cc:dd:ee:ff"},
        )
        assert cmd.device_id == "momo-001"
        assert cmd.cmd == "deauth"
        assert cmd.params["target"] == "aa:bb:cc:dd:ee:ff"
        assert cmd.priority == Priority.HIGH


class TestRoutingResult:
    """Tests for RoutingResult model."""

    def test_successful_result(self) -> None:
        """Test successful routing result."""
        result = RoutingResult(
            message_id="abc123",
            success=True,
            channel=ChannelType.LORA,
            duration_ms=50.0,
        )
        assert result.success is True
        assert result.channel == ChannelType.LORA

    def test_failed_result(self) -> None:
        """Test failed routing result."""
        result = RoutingResult(
            message_id="abc123",
            success=False,
            queued=True,
            error="All channels down",
        )
        assert result.success is False
        assert result.queued is True

