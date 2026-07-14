"""
Tests for channel implementations.
"""

import asyncio

import pytest

from nexus.channels.base import BaseChannel, ChannelError
from nexus.channels.mock import LoopbackChannel, MockChannel, UnreliableChannel
from nexus.domain.enums import ChannelStatus, ChannelType, MessageType
from nexus.domain.models import Message


class TestMockChannel:
    """Tests for MockChannel."""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Test connection lifecycle."""
        channel = MockChannel()

        assert channel.is_connected is False

        await channel.connect()
        assert channel.is_connected is True
        assert channel.status == ChannelStatus.UP

        await channel.disconnect()
        assert channel.is_connected is False

    @pytest.mark.asyncio
    async def test_send_message(self) -> None:
        """Test sending a message."""
        channel = MockChannel(latency_ms=10)
        await channel.connect()

        msg = Message(src="nexus", dst="momo-001", type=MessageType.PING)
        success = await channel.send(msg)

        assert success is True
        assert len(channel.sent_messages) == 1
        assert channel.sent_messages[0].id == msg.id

    @pytest.mark.asyncio
    async def test_send_not_connected(self) -> None:
        """Test sending when not connected raises error."""
        channel = MockChannel()

        msg = Message(src="nexus", type=MessageType.PING)

        with pytest.raises(ChannelError):
            await channel.send(msg)

    @pytest.mark.asyncio
    async def test_simulated_failure(self) -> None:
        """Test simulated failures."""
        channel = MockChannel(failure_rate=1.0)  # 100% failure
        await channel.connect()

        msg = Message(src="nexus", type=MessageType.PING)
        success = await channel.send(msg)

        assert success is False

    @pytest.mark.asyncio
    async def test_latency_simulation(self) -> None:
        """Test latency simulation."""
        channel = MockChannel(latency_ms=100)
        await channel.connect()

        msg = Message(src="nexus", type=MessageType.PING)

        start = asyncio.get_event_loop().time()
        await channel.send(msg)
        elapsed = (asyncio.get_event_loop().time() - start) * 1000

        # Should take at least 100ms (with some margin for jitter)
        assert elapsed >= 90

    @pytest.mark.asyncio
    async def test_inject_message(self) -> None:
        """Test injecting a message for testing."""
        channel = MockChannel()
        await channel.connect()

        received = []

        async def handler(msg: Message):
            received.append(msg)

        channel.add_message_handler(handler)

        msg = Message(src="momo-001", type=MessageType.STATUS)
        await channel.inject_message(msg)

        assert len(received) == 1
        assert received[0].id == msg.id

    @pytest.mark.asyncio
    async def test_clear_messages(self) -> None:
        """Test clearing message history."""
        channel = MockChannel()
        await channel.connect()

        msg = Message(src="nexus", type=MessageType.PING)
        await channel.send(msg)

        assert len(channel.sent_messages) == 1

        channel.clear_messages()
        assert len(channel.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_metrics_update(self) -> None:
        """Test that metrics are updated after send."""
        channel = MockChannel(latency_ms=10)
        await channel.connect()

        msg = Message(src="nexus", type=MessageType.PING)
        await channel.send(msg)

        assert channel.metrics.messages_sent == 1
        assert channel.metrics.latency_ms > 0
        assert channel.metrics.last_success is not None

    @pytest.mark.asyncio
    async def test_to_model(self) -> None:
        """Test converting to Channel model."""
        channel = MockChannel(name="test-channel")
        await channel.connect()

        model = channel.to_model()

        assert model.name == "test-channel"
        assert model.type == ChannelType.MOCK
        assert model.status == ChannelStatus.UP


class TestLoopbackChannel:
    """Tests for LoopbackChannel."""

    @pytest.mark.asyncio
    async def test_echo(self) -> None:
        """Test that messages are echoed back."""
        channel = LoopbackChannel()
        await channel.connect()

        received = []

        async def handler(msg: Message):
            received.append(msg)

        channel.add_message_handler(handler)

        msg = Message(
            src="nexus",
            dst="momo-001",
            type=MessageType.PING,
        )
        await channel.send(msg)

        # Wait for echo
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].src == "momo-001"
        assert received[0].dst == "nexus"


class TestUnreliableChannel:
    """Tests for UnreliableChannel."""

    @pytest.mark.asyncio
    async def test_high_failure_rate(self) -> None:
        """Test that unreliable channel has failures."""
        from nexus.channels.base import ChannelError

        channel = UnreliableChannel(failure_rate=0.7)
        await channel.connect()

        success_count = 0
        failure_count = 0
        total = 20

        for _ in range(total):
            msg = Message(src="nexus", type=MessageType.PING)
            try:
                if await channel.send(msg):
                    success_count += 1
                else:
                    failure_count += 1
            except ChannelError:
                # Channel went DOWN after too many failures
                failure_count += 1

        # With 70% failure rate, expect some failures
        assert failure_count > 0  # Should have at least some failures


class TestChannelStatusTransitions:
    """Tests for channel status state machine."""

    @pytest.mark.asyncio
    async def test_degraded_after_failures(self) -> None:
        """Test channel becomes degraded after failures."""
        channel = MockChannel(failure_rate=1.0)
        await channel.connect()

        # Trigger failures to cause degradation
        channel._failure_threshold_degraded = 2
        for _ in range(3):
            try:
                msg = Message(src="nexus", type=MessageType.PING)
                await channel.send(msg)
            except:
                pass

        assert channel.status == ChannelStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_recovery_after_success(self) -> None:
        """Test channel recovers after successful send."""
        channel = MockChannel()
        await channel.connect()

        # Manually degrade
        channel._status = ChannelStatus.DEGRADED

        # Successful send should recover
        msg = Message(src="nexus", type=MessageType.PING)
        await channel.send(msg)

        assert channel.status == ChannelStatus.UP

