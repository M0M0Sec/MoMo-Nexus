"""
Health Monitor.

Tracks device health, detects offline devices, manages heartbeats.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from nexus.config import NexusConfig, get_config
from nexus.core.events import EventBus, EventType, get_event_bus
from nexus.domain.enums import DeviceStatus
from nexus.fleet.registry import DeviceRegistry

logger = logging.getLogger(__name__)


@dataclass
class DeviceHealth:
    """Health information for a device."""

    device_id: str
    last_seen: datetime | None = None
    last_heartbeat: datetime | None = None
    consecutive_misses: int = 0
    latency_ms: float = 0
    battery: int | None = None
    cpu: int | None = None
    memory: int | None = None
    uptime: int | None = None
    health_score: float = 100.0  # 0-100
    issues: list[str] = field(default_factory=list)


class HealthMonitor:
    """
    Monitors device health and availability.

    Responsibilities:
    - Track heartbeats
    - Detect offline devices
    - Calculate health scores
    - Emit alerts for unhealthy devices
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        config: NexusConfig | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._registry = registry
        self._config = config or get_config()
        self._event_bus = event_bus or get_event_bus()

        # Health data per device
        self._health: dict[str, DeviceHealth] = {}
        self._lock = asyncio.Lock()

        # Timers from config
        self._heartbeat_interval = self._config.fleet.heartbeat_interval
        self._heartbeat_timeout = self._config.fleet.heartbeat_timeout
        self._lost_timeout = self._config.fleet.lost_timeout

        # Monitor task
        self._running = False
        self._monitor_task: asyncio.Task | None = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start health monitoring."""
        if self._running:
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started")

    async def stop(self) -> None:
        """Stop health monitoring."""
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

        logger.info("Health monitor stopped")

    # =========================================================================
    # Heartbeat Handling
    # =========================================================================

    async def process_heartbeat(
        self,
        device_id: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """
        Process heartbeat from device.

        Args:
            device_id: Device ID
            data: Optional status data (battery, cpu, etc.)
        """
        now = datetime.now()
        data = data or {}

        async with self._lock:
            if device_id not in self._health:
                self._health[device_id] = DeviceHealth(device_id=device_id)

            health = self._health[device_id]

            # Calculate latency if we have last heartbeat
            if health.last_heartbeat:
                expected = health.last_heartbeat + timedelta(seconds=self._heartbeat_interval)
                if now > expected:
                    health.latency_ms = (now - expected).total_seconds() * 1000
                else:
                    health.latency_ms = 0

            health.last_heartbeat = now
            health.last_seen = now
            health.consecutive_misses = 0

            # Update health data
            if "battery" in data:
                health.battery = data["battery"]
            if "cpu" in data:
                health.cpu = data["cpu"]
            if "memory" in data:
                health.memory = data["memory"]
            if "uptime" in data:
                health.uptime = data["uptime"]

            # Recalculate health score
            health.health_score = self._calculate_health_score(health)
            health.issues = self._detect_issues(health)

        # Update registry
        await self._registry.update_last_seen(device_id)
        await self._registry.update(
            device_id,
            status=DeviceStatus.ONLINE,
            battery=data.get("battery"),
        )

        logger.debug(f"Heartbeat from {device_id}, score: {health.health_score:.1f}")

    async def record_message(self, device_id: str) -> None:
        """Record that we received a message from device."""
        async with self._lock:
            if device_id not in self._health:
                self._health[device_id] = DeviceHealth(device_id=device_id)

            self._health[device_id].last_seen = datetime.now()

        await self._registry.update_last_seen(device_id)

    # =========================================================================
    # Health Queries
    # =========================================================================

    async def get_health(self, device_id: str) -> DeviceHealth | None:
        """Get health info for a device."""
        async with self._lock:
            return self._health.get(device_id)

    async def get_all_health(self) -> dict[str, DeviceHealth]:
        """Get health info for all devices."""
        async with self._lock:
            return dict(self._health)

    async def is_healthy(self, device_id: str) -> bool:
        """Check if device is healthy."""
        health = await self.get_health(device_id)
        if not health:
            return False
        return health.health_score >= 50.0 and health.consecutive_misses < 3

    async def get_unhealthy_devices(self) -> list[str]:
        """Get list of unhealthy device IDs."""
        async with self._lock:
            return [
                device_id
                for device_id, health in self._health.items()
                if health.health_score < 50.0 or health.consecutive_misses >= 3
            ]

    # =========================================================================
    # Health Calculation
    # =========================================================================

    def _calculate_health_score(self, health: DeviceHealth) -> float:
        """
        Calculate health score (0-100).

        Factors:
        - Heartbeat regularity
        - Battery level
        - Resource usage
        - Latency
        """
        score = 100.0

        # Penalize for missed heartbeats
        score -= health.consecutive_misses * 15

        # Penalize for high latency
        if health.latency_ms > 5000:
            score -= 20
        elif health.latency_ms > 2000:
            score -= 10
        elif health.latency_ms > 1000:
            score -= 5

        # Penalize for low battery
        if health.battery is not None:
            if health.battery < 10:
                score -= 30
            elif health.battery < 20:
                score -= 20
            elif health.battery < 30:
                score -= 10

        # Penalize for high CPU
        if health.cpu is not None:
            if health.cpu > 90:
                score -= 15
            elif health.cpu > 80:
                score -= 10

        # Penalize for high memory
        if health.memory is not None and health.memory > 90:
            score -= 10

        return max(0.0, min(100.0, score))

    def _detect_issues(self, health: DeviceHealth) -> list[str]:
        """Detect health issues."""
        issues = []

        if health.consecutive_misses >= 3:
            issues.append("Missing heartbeats")

        if health.battery is not None and health.battery < 20:
            issues.append(f"Low battery: {health.battery}%")

        if health.cpu is not None and health.cpu > 80:
            issues.append(f"High CPU: {health.cpu}%")

        if health.latency_ms > 5000:
            issues.append(f"High latency: {health.latency_ms:.0f}ms")

        return issues

    # =========================================================================
    # Monitor Loop
    # =========================================================================

    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._check_devices()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")

    async def _check_devices(self) -> None:
        """Check all devices for health issues."""
        now = datetime.now()
        devices = await self._registry.get_all()

        for device in devices:
            if device.status == DeviceStatus.UNREGISTERED:
                continue

            async with self._lock:
                if device.id not in self._health:
                    self._health[device.id] = DeviceHealth(
                        device_id=device.id,
                        last_seen=device.last_seen,
                    )

                health = self._health[device.id]

            # Check if device missed heartbeat
            last_contact = health.last_seen or device.last_seen
            if last_contact:
                time_since = (now - last_contact).total_seconds()

                # Mark offline
                if time_since > self._heartbeat_timeout:
                    # Count EVERY missed check (not just the ONLINE→OFFLINE transition)
                    # so consecutive_misses reflects reality, and mutate it under the lock
                    # (process_heartbeat resets it under the same lock — this was racy).
                    async with self._lock:
                        health.consecutive_misses += 1

                    if device.status == DeviceStatus.ONLINE:
                        await self._registry.set_status(device.id, DeviceStatus.OFFLINE)

                        await self._event_bus.emit(
                            EventType.DEVICE_OFFLINE,
                            {
                                "device_id": device.id,
                                "last_seen": last_contact.isoformat(),
                                "seconds_ago": time_since,
                            },
                        )

                        logger.warning(f"Device offline: {device.id} (last seen {time_since:.0f}s ago)")

                # Mark lost
                if time_since > self._lost_timeout:
                    if device.status != DeviceStatus.LOST:
                        await self._registry.set_status(device.id, DeviceStatus.LOST)

                        await self._event_bus.emit(
                            EventType.DEVICE_LOST,
                            {
                                "device_id": device.id,
                                "last_seen": last_contact.isoformat(),
                                "seconds_ago": time_since,
                            },
                        )

                        logger.error(f"Device lost: {device.id} (no contact for {time_since/3600:.1f}h)")

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict[str, Any]:
        """Get health statistics."""
        async with self._lock:
            healths = list(self._health.values())

        if not healths:
            return {"devices": 0}

        scores = [h.health_score for h in healths]
        batteries = [h.battery for h in healths if h.battery is not None]

        return {
            "devices": len(healths),
            "avg_health_score": sum(scores) / len(scores),
            "min_health_score": min(scores),
            "avg_battery": sum(batteries) / len(batteries) if batteries else None,
            "unhealthy_count": sum(1 for h in healths if h.health_score < 50),
            "issues_count": sum(len(h.issues) for h in healths),
        }

