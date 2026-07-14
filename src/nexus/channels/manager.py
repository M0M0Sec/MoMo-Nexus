"""
Channel Manager.

Orchestrates all communication channels, handles health monitoring,
and provides unified access to channel operations.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Any

from nexus.channels.base import BaseChannel
from nexus.channels.ble import BLEChannel
from nexus.channels.cellular import CellularChannel
from nexus.channels.lora import LoRaChannel
from nexus.channels.wifi import WiFiChannel
from nexus.config import NexusConfig, get_config
from nexus.core.events import EventBus, EventType, get_event_bus
from nexus.domain.enums import ChannelStatus, ChannelType

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Manages all communication channels.

    Responsibilities:
    - Channel lifecycle (init, connect, disconnect)
    - Health monitoring
    - Status reporting
    - Event emission for channel state changes
    """

    def __init__(
        self,
        config: NexusConfig | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._config = config or get_config()
        self._event_bus = event_bus or get_event_bus()
        self._channels: dict[ChannelType, BaseChannel] = {}
        self._running = False
        self._health_task: asyncio.Task | None = None

        # Channel health history
        self._health_history: dict[ChannelType, list[tuple[datetime, bool]]] = {}

        # Last observed status per channel, so the monitor can detect transitions
        # across iterations (it previously compared a value to itself — dead code).
        self._last_status: dict[ChannelType, ChannelStatus] = {}

        # Strong refs to recovery tasks so they aren't garbage-collected mid-run.
        self._recovery_tasks: set[asyncio.Task] = set()

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def channels(self) -> dict[ChannelType, BaseChannel]:
        """Get all registered channels."""
        return self._channels.copy()

    @property
    def available_channels(self) -> list[BaseChannel]:
        """Get channels that are available for sending."""
        return [ch for ch in self._channels.values() if ch.is_available()]

    # =========================================================================
    # Channel Management
    # =========================================================================

    def register_channel(self, channel: BaseChannel) -> None:
        """
        Register a channel.

        Args:
            channel: Channel instance to register
        """
        self._channels[channel.channel_type] = channel
        self._health_history[channel.channel_type] = []
        logger.info(f"Registered channel: {channel.name}")

    def unregister_channel(self, channel_type: ChannelType) -> None:
        """Unregister a channel."""
        if channel_type in self._channels:
            del self._channels[channel_type]
            self._health_history.pop(channel_type, None)
            logger.info(f"Unregistered channel: {channel_type.value}")

    def get_channel(self, channel_type: ChannelType) -> BaseChannel | None:
        """Get channel by type."""
        return self._channels.get(channel_type)

    async def create_channels_from_config(self) -> None:
        """Create and register channels based on configuration."""
        cfg = self._config.channels

        # LoRa
        if cfg.lora.enabled:
            channel = LoRaChannel(
                serial_port=cfg.lora.serial_port,
                channel_name=cfg.lora.channel_name,
                psk=cfg.lora.psk,
            )
            self.register_channel(channel)

        # Cellular
        if cfg.cellular.enabled:
            channel = CellularChannel(
                serial_port=cfg.cellular.serial_port,
                baud_rate=cfg.cellular.baud_rate,
                apn=cfg.cellular.apn,
                api_endpoint=cfg.cellular.api_endpoint,
                pin=cfg.cellular.pin,
            )
            self.register_channel(channel)

        # WiFi
        if cfg.wifi.enabled:
            channel = WiFiChannel(
                ssid=cfg.wifi.ssid,
                password=cfg.wifi.password,
                interface=cfg.wifi.interface,
            )
            self.register_channel(channel)

        # BLE
        if cfg.ble.enabled:
            channel = BLEChannel(
                adapter=cfg.ble.adapter,
                service_uuid=cfg.ble.service_uuid,
            )
            self.register_channel(channel)

        logger.info(f"Created {len(self._channels)} channels from config")

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start all channels and health monitoring."""
        if self._running:
            return

        self._running = True

        # Connect all channels
        for channel_type, channel in self._channels.items():
            try:
                logger.info(f"Connecting channel: {channel.name}")
                await channel.connect()

                # Start health check
                await channel.start_health_check()

                # Emit event
                await self._event_bus.emit(
                    EventType.CHANNEL_UP,
                    {"channel": channel_type.value, "name": channel.name},
                )

            except Exception as e:
                logger.error(f"Failed to connect {channel.name}: {e}")
                await self._event_bus.emit(
                    EventType.CHANNEL_DOWN,
                    {"channel": channel_type.value, "error": str(e)},
                )

        # Start health monitoring
        self._health_task = asyncio.create_task(self._health_monitor())

        logger.info(f"Channel manager started, {len(self.available_channels)} channels available")

    async def stop(self) -> None:
        """Stop all channels and health monitoring."""
        self._running = False

        # Stop health monitoring
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None

        # Disconnect all channels
        for channel in self._channels.values():
            try:
                await channel.stop_health_check()
                await channel.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting {channel.name}: {e}")

        logger.info("Channel manager stopped")

    async def restart_channel(self, channel_type: ChannelType) -> bool:
        """
        Restart a specific channel.

        Args:
            channel_type: Channel to restart

        Returns:
            True if restart successful
        """
        channel = self._channels.get(channel_type)
        if not channel:
            return False

        try:
            logger.info(f"Restarting channel: {channel.name}")

            await channel.stop_health_check()
            await channel.disconnect()

            await asyncio.sleep(1)

            await channel.connect()
            await channel.start_health_check()

            await self._event_bus.emit(
                EventType.CHANNEL_UP,
                {"channel": channel_type.value, "restarted": True},
            )

            return True

        except Exception as e:
            logger.error(f"Failed to restart {channel.name}: {e}")
            await self._event_bus.emit(
                EventType.CHANNEL_DOWN,
                {"channel": channel_type.value, "error": str(e)},
            )
            return False

    # =========================================================================
    # Health Monitoring
    # =========================================================================

    async def _health_monitor(self) -> None:
        """Background health monitoring loop."""
        logger.info("Health monitor started")

        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                await self._check_health_once()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")

        logger.info("Health monitor stopped")

    async def _check_health_once(self) -> None:
        """Run a single health-check pass: detect status transitions, emit events,
        and schedule recovery for channels that went DOWN.

        Extracted from the monitor loop so it can be unit-tested without the 30s sleep.
        """
        for channel_type, channel in self._channels.items():
            # Compare the channel's CURRENT status against the value recorded on the
            # previous pass — a real transition, not value-vs-itself (the old bug).
            new_status = channel.status
            old_status = self._last_status.get(channel_type, new_status)
            self._last_status[channel_type] = new_status

            # Record health history
            is_healthy = new_status == ChannelStatus.UP
            self._health_history[channel_type].append((datetime.now(), is_healthy))
            if len(self._health_history[channel_type]) > 100:
                self._health_history[channel_type] = self._health_history[channel_type][-100:]

            # Emit events on status change
            if old_status == new_status:
                continue

            if new_status == ChannelStatus.UP:
                await self._event_bus.emit(
                    EventType.CHANNEL_UP, {"channel": channel_type.value}
                )
            elif new_status == ChannelStatus.DEGRADED:
                await self._event_bus.emit(
                    EventType.CHANNEL_DEGRADED, {"channel": channel_type.value}
                )
            elif new_status == ChannelStatus.DOWN:
                await self._event_bus.emit(
                    EventType.CHANNEL_DOWN, {"channel": channel_type.value}
                )
                # Try to restart down channels (keep a strong task ref).
                if self._running:
                    task = asyncio.create_task(self._try_recover_channel(channel_type))
                    self._recovery_tasks.add(task)
                    task.add_done_callback(self._recovery_tasks.discard)

    async def _try_recover_channel(self, channel_type: ChannelType) -> None:
        """Attempt to recover a failed channel."""
        channel = self._channels.get(channel_type)
        if not channel:
            return

        logger.info(f"Attempting to recover channel: {channel.name}")

        for attempt in range(3):
            await asyncio.sleep(5 * (attempt + 1))  # Backoff

            try:
                await channel.disconnect()
                await asyncio.sleep(1)
                await channel.connect()

                if channel.status == ChannelStatus.UP:
                    logger.info(f"Channel recovered: {channel.name}")
                    return

            except Exception as e:
                logger.warning(f"Recovery attempt {attempt + 1} failed for {channel.name}: {e}")

        logger.error(f"Failed to recover channel: {channel.name}")

    # =========================================================================
    # Status & Metrics
    # =========================================================================

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        status = {
            "total": len(self._channels),
            "available": len(self.available_channels),
            "channels": {},
        }

        for channel_type, channel in self._channels.items():
            status["channels"][channel_type.value] = {
                "name": channel.name,
                "status": channel.status.value,
                "connected": channel.is_connected,
                "available": channel.is_available(),
                "enabled": channel.enabled,
                "metrics": {
                    "latency_ms": channel.metrics.latency_ms,
                    "messages_sent": channel.metrics.messages_sent,
                    "messages_received": channel.metrics.messages_received,
                    "bytes_sent": channel.metrics.bytes_sent,
                    "bytes_received": channel.metrics.bytes_received,
                    "last_success": (
                        channel.metrics.last_success.isoformat()
                        if channel.metrics.last_success
                        else None
                    ),
                    "consecutive_failures": channel.metrics.consecutive_failures,
                },
            }

        return status

    def get_health_summary(self) -> dict[str, Any]:
        """Get health summary with uptime statistics."""
        summary = {}

        for channel_type, history in self._health_history.items():
            if not history:
                continue

            total = len(history)
            healthy = sum(1 for _, h in history if h)
            uptime_pct = (healthy / total * 100) if total > 0 else 0

            summary[channel_type.value] = {
                "uptime_percent": round(uptime_pct, 2),
                "total_checks": total,
                "healthy_checks": healthy,
                "current_status": self._channels[channel_type].status.value,
            }

        return summary

    def get_best_channel(self, exclude: list[ChannelType] | None = None) -> BaseChannel | None:
        """
        Get the best available channel.

        Args:
            exclude: Channel types to exclude

        Returns:
            Best available channel or None
        """
        exclude = exclude or []
        available = [
            ch for ct, ch in self._channels.items() if ch.is_available() and ct not in exclude
        ]

        if not available:
            return None

        # Sort by score (lower is better)
        available.sort(key=lambda ch: ch.to_model().score())
        return available[0]

