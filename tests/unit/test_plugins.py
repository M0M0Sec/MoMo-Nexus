"""
Tests for plugin system.
"""

import pytest

from nexus.config import NexusConfig
from nexus.core.events import EventBus
from nexus.plugins.base import Plugin, PluginCapability, PluginMetadata, PluginState
from nexus.plugins.hooks import HookRegistry, HookType, hook
from nexus.plugins.manager import PluginManager

# =============================================================================
# Test Plugin
# =============================================================================


class SamplePlugin(Plugin):
    """A sample plugin for unit tests."""

    metadata = PluginMetadata(
        id="sample-plugin",
        name="Sample Plugin",
        version="1.0.0",
        description="A plugin for testing",
        capabilities=[PluginCapability.MESSAGE_HANDLER],
    )

    def __init__(self) -> None:
        super().__init__()
        self.load_called = False
        self.start_called = False
        self.stop_called = False
        self.messages_received = []

    async def on_load(self) -> None:
        self.load_called = True

    async def on_start(self) -> None:
        self.start_called = True

    async def on_stop(self) -> None:
        self.stop_called = True

    @hook(HookType.MESSAGE_RECEIVED, priority=10)
    async def handle_message(self, message: dict) -> None:
        self.messages_received.append(message)


class FailingPlugin(Plugin):
    """A plugin that fails on load."""

    metadata = PluginMetadata(
        id="failing-plugin",
        name="Failing Plugin",
        version="1.0.0",
    )

    async def on_load(self) -> None:
        raise RuntimeError("Intentional failure")


# =============================================================================
# Tests
# =============================================================================


class TestPluginBase:
    """Tests for Plugin base class."""

    def test_plugin_metadata(self) -> None:
        """Test plugin metadata."""
        plugin = SamplePlugin()
        assert plugin.id == "sample-plugin"
        assert plugin.name == "Sample Plugin"
        assert plugin.version == "1.0.0"

    def test_plugin_initial_state(self) -> None:
        """Test initial plugin state."""
        plugin = SamplePlugin()
        assert plugin.state == PluginState.UNLOADED
        assert not plugin.is_running

    @pytest.mark.asyncio
    async def test_plugin_lifecycle(self) -> None:
        """Test plugin lifecycle methods."""
        plugin = SamplePlugin()
        config = NexusConfig()
        event_bus = EventBus()

        # Load
        await plugin._load({}, config, event_bus)
        assert plugin.state == PluginState.LOADED
        assert plugin.load_called

        # Start
        await plugin._start()
        assert plugin.state == PluginState.RUNNING
        assert plugin.start_called
        assert plugin.is_running

        # Stop
        await plugin._stop()
        assert plugin.state == PluginState.STOPPED
        assert plugin.stop_called

        # Unload
        await plugin._unload()
        assert plugin.state == PluginState.UNLOADED

    @pytest.mark.asyncio
    async def test_plugin_config(self) -> None:
        """Test plugin configuration."""
        plugin = SamplePlugin()
        config = NexusConfig()
        event_bus = EventBus()

        plugin_config = {"key": "value", "number": 42}
        await plugin._load(plugin_config, config, event_bus)

        assert plugin.config["key"] == "value"
        assert plugin.config["number"] == 42

    def test_plugin_status(self) -> None:
        """Test plugin status."""
        plugin = SamplePlugin()
        status = plugin.get_status()

        assert status["id"] == "sample-plugin"
        assert status["state"] == "unloaded"


class TestHookRegistry:
    """Tests for HookRegistry."""

    @pytest.fixture
    def registry(self) -> HookRegistry:
        """Create hook registry."""
        return HookRegistry()

    @pytest.mark.asyncio
    async def test_register_hook(self, registry: HookRegistry) -> None:
        """Test hook registration."""
        async def handler(msg):
            pass

        hook = await registry.register(
            HookType.MESSAGE_RECEIVED,
            handler,
            "sample-plugin",
        )

        assert hook.hook_type == HookType.MESSAGE_RECEIVED
        assert hook.plugin_id == "sample-plugin"

    @pytest.mark.asyncio
    async def test_call_hooks(self, registry: HookRegistry) -> None:
        """Test calling hooks."""
        results = []

        async def handler1(value):
            results.append("handler1")
            return "result1"

        async def handler2(value):
            results.append("handler2")
            return "result2"

        await registry.register(HookType.MESSAGE_RECEIVED, handler1, "p1")
        await registry.register(HookType.MESSAGE_RECEIVED, handler2, "p2")

        hook_results = await registry.call(HookType.MESSAGE_RECEIVED, "test")

        assert len(results) == 2
        assert len(hook_results) == 2

    @pytest.mark.asyncio
    async def test_hook_priority(self, registry: HookRegistry) -> None:
        """Test hook priority ordering."""
        order = []

        async def handler_low(v):
            order.append("low")

        async def handler_high(v):
            order.append("high")

        # Register in reverse priority order
        await registry.register(HookType.MESSAGE_RECEIVED, handler_low, "p1", priority=90)
        await registry.register(HookType.MESSAGE_RECEIVED, handler_high, "p2", priority=10)

        await registry.call(HookType.MESSAGE_RECEIVED, "test")

        # High priority (10) should run before low (90)
        assert order == ["high", "low"]

    @pytest.mark.asyncio
    async def test_call_filter(self, registry: HookRegistry) -> None:
        """Test filter hooks."""
        async def add_prefix(value):
            return f"prefix_{value}"

        async def add_suffix(value):
            return f"{value}_suffix"

        await registry.register(HookType.MESSAGE_FILTER, add_prefix, "p1", priority=10)
        await registry.register(HookType.MESSAGE_FILTER, add_suffix, "p2", priority=20)

        result = await registry.call_filter(HookType.MESSAGE_FILTER, "test")

        assert result == "prefix_test_suffix"

    @pytest.mark.asyncio
    async def test_unregister_plugin(self, registry: HookRegistry) -> None:
        """Test unregistering all hooks for a plugin."""
        async def handler(v):
            pass

        await registry.register(HookType.MESSAGE_RECEIVED, handler, "plugin-1")
        await registry.register(HookType.MESSAGE_POST_SEND, handler, "plugin-1")
        await registry.register(HookType.MESSAGE_RECEIVED, handler, "plugin-2")

        count = await registry.unregister_plugin("plugin-1")

        assert count == 2

        remaining = await registry.count()
        assert remaining == 1


class TestPluginManager:
    """Tests for PluginManager."""

    @pytest.fixture
    def manager(self) -> PluginManager:
        """Create plugin manager."""
        config = NexusConfig()
        event_bus = EventBus()
        hook_registry = HookRegistry()
        return PluginManager(
            config=config,
            event_bus=event_bus,
            hook_registry=hook_registry,
        )

    @pytest.mark.asyncio
    async def test_load_plugin(self, manager: PluginManager) -> None:
        """Test loading a plugin."""
        plugin = await manager.load(SamplePlugin)

        assert plugin is not None
        assert plugin.id == "sample-plugin"
        assert plugin.state == PluginState.LOADED
        assert manager.is_loaded("sample-plugin")

    @pytest.mark.asyncio
    async def test_start_plugin(self, manager: PluginManager) -> None:
        """Test starting a plugin."""
        await manager.load(SamplePlugin)
        result = await manager.start("sample-plugin")

        assert result is True
        assert manager.is_running("sample-plugin")

    @pytest.mark.asyncio
    async def test_stop_plugin(self, manager: PluginManager) -> None:
        """Test stopping a plugin."""
        await manager.load(SamplePlugin)
        await manager.start("sample-plugin")

        result = await manager.stop("sample-plugin")

        assert result is True
        assert not manager.is_running("sample-plugin")

    @pytest.mark.asyncio
    async def test_unload_plugin(self, manager: PluginManager) -> None:
        """Test unloading a plugin."""
        await manager.load(SamplePlugin)
        result = await manager.unload("sample-plugin")

        assert result is True
        assert not manager.is_loaded("sample-plugin")

    @pytest.mark.asyncio
    async def test_load_failing_plugin(self, manager: PluginManager) -> None:
        """Test loading a plugin that fails."""
        plugin = await manager.load(FailingPlugin)

        assert plugin is None

    @pytest.mark.asyncio
    async def test_hooks_registered(self, manager: PluginManager) -> None:
        """Test that plugin hooks are registered."""
        await manager.load(SamplePlugin)

        hooks = await manager._hooks.get_hooks(HookType.MESSAGE_RECEIVED)

        assert len(hooks) == 1
        assert hooks[0].plugin_id == "sample-plugin"

    @pytest.mark.asyncio
    async def test_hooks_unregistered_on_unload(self, manager: PluginManager) -> None:
        """Test that hooks are unregistered when plugin unloads."""
        await manager.load(SamplePlugin)
        await manager.unload("sample-plugin")

        hooks = await manager._hooks.get_hooks(HookType.MESSAGE_RECEIVED)

        assert len(hooks) == 0

    @pytest.mark.asyncio
    async def test_start_stop_all(self, manager: PluginManager) -> None:
        """Test starting and stopping all plugins."""
        await manager.load(SamplePlugin)

        start_results = await manager.start_all()
        assert start_results["sample-plugin"] is True

        running = manager.get_running()
        assert len(running) == 1

        stop_results = await manager.stop_all()
        assert stop_results["sample-plugin"] is True

        running = manager.get_running()
        assert len(running) == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, manager: PluginManager) -> None:
        """Test getting statistics."""
        await manager.load(SamplePlugin)
        await manager.start("sample-plugin")

        stats = await manager.get_stats()

        assert stats["loaded"] == 1
        assert stats["running"] == 1
        assert stats["hooks_registered"] >= 1

