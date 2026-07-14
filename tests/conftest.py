"""
Pytest configuration and fixtures.
"""

import asyncio
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio

from nexus.channels.mock import MockChannel
from nexus.config import NexusConfig
from nexus.core.events import EventBus
from nexus.core.router import Router
from nexus.domain.enums import MessageType, Priority
from nexus.domain.models import Device, Message
from nexus.infrastructure.database import DeviceStore, MessageStore


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def config() -> NexusConfig:
    """Create test configuration."""
    return NexusConfig(
        device_id="nexus-test",
        name="Test Nexus",
    )


@pytest.fixture
def event_bus() -> EventBus:
    """Create fresh event bus."""
    return EventBus()


@pytest.fixture
def mock_channel() -> MockChannel:
    """Create mock channel."""
    return MockChannel(
        name="test-mock",
        latency_ms=10.0,
        failure_rate=0.0,
    )


@pytest_asyncio.fixture
async def connected_channel() -> AsyncGenerator[MockChannel, None]:
    """Create and connect a mock channel."""
    channel = MockChannel(name="connected-mock", latency_ms=5.0)
    await channel.connect()
    yield channel
    await channel.disconnect()


@pytest.fixture
def router(config: NexusConfig, event_bus: EventBus) -> Router:
    """Create router."""
    return Router(config=config, event_bus=event_bus)


@pytest_asyncio.fixture
async def router_with_channel(
    router: Router,
    connected_channel: MockChannel,
) -> AsyncGenerator[Router, None]:
    """Create router with connected mock channel."""
    router.register_channel(connected_channel)
    yield router


@pytest.fixture
def sample_message() -> Message:
    """Create sample message."""
    return Message(
        src="momo-001",
        dst="nexus",
        type=MessageType.STATUS,
        pri=Priority.NORMAL,
        data={"status": "ok", "battery": 85},
    )


@pytest.fixture
def sample_device() -> Device:
    """Create sample device."""
    from nexus.domain.enums import DeviceStatus, DeviceType

    return Device(
        id="momo-001",
        type=DeviceType.MOMO,
        name="Test MoMo",
        status=DeviceStatus.ONLINE,
    )


@pytest_asyncio.fixture
async def message_store() -> AsyncGenerator[MessageStore, None]:
    """Create temporary message store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = MessageStore(str(db_path))
        await store.connect()
        yield store
        await store.disconnect()


@pytest_asyncio.fixture
async def device_store() -> AsyncGenerator[DeviceStore, None]:
    """Create temporary device store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = DeviceStore(str(db_path))
        await store.connect()
        yield store
        await store.disconnect()

