"""
MoMo-Swarm Bridge
~~~~~~~~~~~~~~~~~

Bridge module connecting Nexus to LoRa mesh network.
Integrates with Nexus LoRaChannel for actual transmission.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from nexus.swarm.notifications import (
    NotificationBuilder,
    OperatorNotification,
)
from nexus.swarm.protocol import (
    AckStatus,
    CommandCode,
    EventCode,
    SequenceTracker,
    SwarmMessage,
    SwarmMessageBuilder,
    SwarmMessageType,
)

logger = logging.getLogger(__name__)


# Type alias for command handlers
CommandHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class BridgeStats:
    """Statistics for bridge operations."""
    messages_sent: int = 0
    messages_received: int = 0
    commands_executed: int = 0
    alerts_sent: int = 0
    errors: int = 0
    last_heartbeat: float | None = None
    start_time: float = field(default_factory=time.time)

    @property
    def uptime(self) -> int:
        """Get uptime in seconds."""
        return int(time.time() - self.start_time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "commands_executed": self.commands_executed,
            "alerts_sent": self.alerts_sent,
            "errors": self.errors,
            "uptime": self.uptime,
            "last_heartbeat": self.last_heartbeat,
        }


@dataclass
class SwarmConfig:
    """Configuration for Swarm bridge."""
    enabled: bool = True
    device_id: str = "nexus-hub"
    heartbeat_interval: int = 300  # seconds
    alerts_per_minute: int = 10
    sequence_window: int = 100

    # Events to forward from devices
    forward_events: list[str] = field(default_factory=lambda: [
        "handshake_captured",
        "pmkid_captured",
        "crack_complete",
        "evil_twin_connect",
        "credential_captured",
        "ghost_beacon",
        "mimic_trigger",
    ])


class SwarmBridge:
    """
    Bridge between Nexus and LoRa mesh network.

    This class handles:
    - Sending alerts and status updates via LoRa
    - Receiving and routing commands to field devices
    - Rate limiting and message queuing
    - Device tracking and heartbeat management

    Note: Uses Nexus LoRaChannel for actual transmission.

    Example:
        >>> from nexus.channels import LoRaChannel
        >>> lora = LoRaChannel(serial_port="/dev/ttyUSB0")
        >>> bridge = SwarmBridge(lora_channel=lora)
        >>> await bridge.start()
        >>> bridge.send_alert(EventCode.HANDSHAKE_CAPTURED, {
        ...     "ssid": "CORP-WiFi",
        ...     "bssid": "AA:BB:CC:DD:EE:FF"
        ... })
    """

    def __init__(
        self,
        lora_channel: Any = None,  # LoRaChannel
        config: SwarmConfig | None = None,
    ):
        """
        Initialize swarm bridge.

        Args:
            lora_channel: LoRaChannel instance for transmission
            config: Configuration object
        """
        self.config = config or SwarmConfig()
        self._lora = lora_channel
        self.builder = SwarmMessageBuilder(self.config.device_id)
        self.seq_tracker = SequenceTracker(self.config.sequence_window)
        self.stats = BridgeStats()

        # Command handlers
        self._command_handlers: dict[str, CommandHandler] = {}

        # Event callbacks (for forwarding to fleet/dashboard)
        self._event_callbacks: list[EventCallback] = []

        # Rate limiting
        self._alert_times: list[float] = []

        # Known devices
        # LRU-bounded: device_id comes from the (untrusted) message source, so cap it.
        self._devices: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_tracked_devices = 500

        # Tasks
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._running = False

        # Strong refs to fire-and-forget send tasks so they aren't GC'd before
        # completing (and so their failures are surfaced, not silently swallowed).
        self._send_tasks: set[asyncio.Task] = set()

        # Notification builder for operator messages
        self.notify = NotificationBuilder()

    # ==================== Lifecycle ====================

    async def start(self) -> bool:
        """
        Start the swarm bridge.

        Returns:
            True if started successfully
        """
        if not self.config.enabled:
            logger.warning("Swarm bridge is disabled in config")
            return False

        if self._lora is None:
            logger.error("No LoRa channel configured")
            return False

        self._running = True

        # Register message handler on LoRa channel
        if hasattr(self._lora, 'add_message_handler'):
            self._lora.add_message_handler(self._on_lora_message)

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Send startup notification
        self.send_alert(EventCode.STARTUP, {"msg": "Nexus Swarm online"})

        logger.info("Swarm bridge started")
        return True

    async def stop(self) -> None:
        """Stop the swarm bridge."""
        # Send the shutdown notification while still running, and AWAIT the actual send.
        # send_alert() is fire-and-forget and _send_swarm_message() is guarded by
        # `_running`, so the previous order (running=False THEN send_alert) dropped it.
        if self._running and self._lora is not None:
            with contextlib.suppress(Exception):
                await self._send_swarm_message(
                    self.builder.alert(EventCode.SHUTDOWN, {"msg": "Nexus Swarm offline"})
                )

        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        logger.info("Swarm bridge stopped")

    @property
    def is_running(self) -> bool:
        """Check if bridge is running."""
        return self._running

    # ==================== Message Sending ====================

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        now = time.time()

        # Remove old timestamps (older than 1 minute)
        self._alert_times = [t for t in self._alert_times if now - t < 60]

        # Check limit
        if len(self._alert_times) >= self.config.alerts_per_minute:
            logger.warning("Rate limit exceeded, dropping message")
            return False

        self._alert_times.append(now)
        return True

    def _spawn_send(self, msg: SwarmMessage) -> None:
        """Fire-and-forget a swarm send while keeping a strong task ref and logging
        any failure (a bare create_task can be GC'd and swallows exceptions)."""
        task = asyncio.create_task(self._send_swarm_message(msg))
        self._send_tasks.add(task)
        task.add_done_callback(self._on_send_done)

    def _on_send_done(self, task: asyncio.Task) -> None:
        self._send_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Swarm send task failed: %s", task.exception())

    async def _send_swarm_message(self, msg: SwarmMessage) -> bool:
        """
        Send swarm message via LoRa channel.

        Args:
            msg: SwarmMessage to send

        Returns:
            True if sent successfully
        """
        if self._lora is None or not self._running:
            logger.error("Cannot send: LoRa not available")
            return False

        try:
            # Convert to Nexus Message format
            from nexus.domain.enums import MessageType, Priority
            from nexus.domain.models import Message as NexusMessage

            nexus_msg = NexusMessage(
                src=msg.source,
                dst=msg.destination,
                type=MessageType.DATA,  # Swarm uses DATA type
                pri=Priority.NORMAL,
                data={
                    # Embed as a structured dict, NOT a pre-serialized JSON string, so
                    # the outer serialization doesn't double-encode (escaped-string bloat
                    # that can push the payload past the LoRa size limit).
                    "swarm": msg.to_dict()
                },
            )

            # Send via LoRa
            success = await self._lora.send(nexus_msg)

            if success:
                self.stats.messages_sent += 1
                logger.debug(f"Sent swarm: {msg.type.value}/{msg.data.get('evt', msg.data.get('cmd', ''))}")

            return success

        except Exception as e:
            logger.error(f"Swarm send failed: {e}")
            self.stats.errors += 1
            return False

    def send_alert(
        self,
        event: EventCode | str,
        data: dict[str, Any],
        destination: str | None = None
    ) -> bool:
        """
        Send alert message to all listeners.

        Args:
            event: Event code
            data: Event data
            destination: Optional destination device ID

        Returns:
            True if sent successfully
        """
        if not self._check_rate_limit():
            return False

        msg = self.builder.alert(event, data, destination)

        # Fire and forget
        self._spawn_send(msg)
        self.stats.alerts_sent += 1

        return True

    def send_command(
        self,
        cmd: CommandCode | str,
        params: dict[str, Any],
        destination: str
    ) -> bool:
        """
        Send command to a field device.

        Args:
            cmd: Command code
            params: Command parameters
            destination: Target device ID

        Returns:
            True if sent successfully
        """
        msg = self.builder.command(cmd, params, destination)
        self._spawn_send(msg)
        return True

    def send_status(self) -> bool:
        """
        Send status/heartbeat message.

        Returns:
            True if sent successfully
        """
        msg = self.builder.status(
            uptime=self.stats.uptime,
            battery=100,  # Hub is always powered
            temperature=self._get_temperature(),
            gps=(0.0, 0.0),  # Hub typically doesn't have GPS
            aps_seen=len(self._devices),
            handshakes=0,
        )

        self.stats.last_heartbeat = time.time()
        self._spawn_send(msg)
        return True

    # ==================== Operator Notifications ====================

    async def send_notification(self, notification: OperatorNotification) -> bool:
        """
        Send human-readable notification to operator phone.

        Args:
            notification: OperatorNotification object

        Returns:
            True if sent successfully

        Example:
            >>> await bridge.send_notification(
            ...     bridge.notify.handshake_captured("CORP-WiFi")
            ... )
        """
        if not self._check_rate_limit():
            return False

        # Create a simple text message for Meshtastic
        text = notification.to_text(compact=True)

        msg = self.builder.alert(
            EventCode.ALERT,
            {"text": text, "pri": notification.priority},
        )

        success = await self._send_swarm_message(msg)
        if success:
            self.stats.alerts_sent += 1
        return success

    def notify_handshake(self, ssid: str, bssid: str = "") -> bool:
        """Quick: Send handshake captured notification."""
        notification = self.notify.handshake_captured(ssid, bssid)
        asyncio.create_task(self.send_notification(notification))
        return True

    def notify_cracked(self, ssid: str, password: str) -> bool:
        """Quick: Send password cracked notification."""
        notification = self.notify.password_cracked(ssid, password)
        asyncio.create_task(self.send_notification(notification))
        return True

    def notify_credential(
        self,
        cred_type: str,
        username: str = "",
        target: str = ""
    ) -> bool:
        """Quick: Send credential captured notification."""
        notification = self.notify.credential_captured(cred_type, username, target)
        asyncio.create_task(self.send_notification(notification))
        return True

    def notify_device_status(self, device_id: str, online: bool = True) -> bool:
        """Quick: Send device online/offline notification."""
        if online:
            notification = self.notify.device_online(device_id)
        else:
            notification = self.notify.device_offline(device_id)
        asyncio.create_task(self.send_notification(notification))
        return True

    def send_operator_summary(
        self,
        handshakes: int = 0,
        cracked: int = 0,
        alerts: int = 0
    ) -> bool:
        """
        Send status summary to operator phone.

        Args:
            handshakes: Number of handshakes captured
            cracked: Number of passwords cracked
            alerts: Number of alerts

        Returns:
            True if sent

        Example output on phone:
            📊 Durum | D:3 H:12 C:5 A:2
        """
        notification = self.notify.status_summary(
            devices=len(self._devices),
            handshakes=handshakes,
            cracked=cracked,
            alerts=alerts
        )
        asyncio.create_task(self.send_notification(notification))
        return True

    # ==================== Message Receiving ====================

    async def _on_lora_message(self, nexus_msg: Any) -> None:
        """Handle incoming message from LoRa channel."""
        self.stats.messages_received += 1

        try:
            # Check if it's a swarm message
            if "swarm" not in nexus_msg.data:
                return

            swarm_payload = nexus_msg.data["swarm"]
            # New senders embed a dict (no double-encoding); tolerate the legacy
            # JSON-string form for backward compatibility.
            if isinstance(swarm_payload, str):
                msg = SwarmMessage.from_json(swarm_payload)
            else:
                msg = SwarmMessage.from_dict(swarm_payload)

            if not msg:
                logger.warning("Invalid swarm message format")
                return

            # Check destination (if specified)
            if msg.destination and msg.destination != self.config.device_id:
                return  # Not for us

            # Check for replay attacks
            if not self.seq_tracker.is_valid(msg.source, msg.sequence):
                logger.warning(f"Replay attack detected from {msg.source}")
                return

            # Update device tracking
            self._update_device(msg.source, msg)

            # Handle by message type
            if msg.type == SwarmMessageType.CMD:
                await self._handle_command(msg)
            elif msg.type == SwarmMessageType.ALERT:
                await self._handle_alert(msg)
            elif msg.type == SwarmMessageType.STATUS:
                await self._handle_status(msg)
            elif msg.type == SwarmMessageType.GPS:
                await self._handle_gps(msg)
            else:
                logger.debug(f"Received {msg.type.value} from {msg.source}")

        except Exception as e:
            logger.error(f"Swarm receive error: {e}")
            self.stats.errors += 1

    def _update_device(self, device_id: str, msg: SwarmMessage) -> None:
        """Update device tracking info."""
        if device_id not in self._devices:
            # Evict the least-recently-updated device at the cap (bounds spoofed IDs).
            while len(self._devices) >= self._max_tracked_devices:
                self._devices.popitem(last=False)
            self._devices[device_id] = {
                "first_seen": time.time(),
                "message_count": 0,
            }
        self._devices.move_to_end(device_id)  # mark most-recently-updated

        self._devices[device_id].update({
            "last_seen": time.time(),
            "last_message_type": msg.type.value,
            "message_count": self._devices[device_id]["message_count"] + 1,
        })

        # Extract status data if available
        if msg.type == SwarmMessageType.STATUS:
            self._devices[device_id].update({
                "battery": msg.data.get("bat"),
                "temperature": msg.data.get("temp"),
                "gps": msg.data.get("gps"),
                "uptime": msg.data.get("up"),
            })

    async def _handle_command(self, msg: SwarmMessage) -> None:
        """Handle incoming command."""
        cmd = msg.data.get('cmd')
        params = {k: v for k, v in msg.data.items() if k != 'cmd'}

        logger.info(f"Received command: {cmd} from {msg.source}")
        self.stats.commands_executed += 1

        try:
            if cmd in self._command_handlers:
                handler = self._command_handlers[cmd]
                result = await handler(params)

                # Send ack
                ack_status = AckStatus.ERROR if result.get('error') else AckStatus.OK
                ack_msg = self.builder.ack(
                    msg.sequence,
                    ack_status,
                    msg.source,
                    result=result.get('result'),
                    error=result.get('error'),
                )
                await self._send_swarm_message(ack_msg)
            else:
                # Forward to event callbacks
                for callback in self._event_callbacks:
                    try:
                        await callback(cmd, params)
                    except Exception as e:
                        logger.error(f"Event callback error: {e}")

        except Exception as e:
            logger.error(f"Command execution failed: {e}")

    async def _handle_alert(self, msg: SwarmMessage) -> None:
        """Handle incoming alert from field device."""
        event = msg.data.get('evt', 'unknown')
        logger.info(f"Alert from {msg.source}: {event}")

        # Forward to event callbacks
        for callback in self._event_callbacks:
            try:
                await callback(event, msg.data)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    async def _handle_status(self, msg: SwarmMessage) -> None:
        """Handle incoming status from field device."""
        logger.debug(f"Status from {msg.source}: bat={msg.data.get('bat')}%, temp={msg.data.get('temp')}°C")

    async def _handle_gps(self, msg: SwarmMessage) -> None:
        """Handle incoming GPS update."""
        lat = msg.data.get('lat', 0)
        lon = msg.data.get('lon', 0)
        logger.debug(f"GPS from {msg.source}: ({lat}, {lon})")

        # Update device location
        if msg.source in self._devices:
            self._devices[msg.source]["gps"] = [lat, lon]

    # ==================== Command Registration ====================

    def register_command(self, cmd: CommandCode | str, handler: CommandHandler) -> None:
        """
        Register a command handler.

        Args:
            cmd: Command code to handle
            handler: Async function that takes params and returns result dict
        """
        key = cmd.value if isinstance(cmd, CommandCode) else cmd
        self._command_handlers[key] = handler

    def on_event(self, callback: EventCallback) -> None:
        """
        Register callback for incoming events/alerts.

        Args:
            callback: Async function(event_type, data)
        """
        self._event_callbacks.append(callback)

    # ==================== Device Management ====================

    def get_devices(self) -> dict[str, dict[str, Any]]:
        """Get all known devices."""
        return self._devices.copy()

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        """Get info for a specific device."""
        return self._devices.get(device_id)

    # ==================== Heartbeat ====================

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat sender."""
        while self._running:
            try:
                await asyncio.sleep(self.config.heartbeat_interval)

                if self._running:
                    self.send_status()
                    logger.debug("Swarm heartbeat sent")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                self.stats.errors += 1

    # ==================== Helpers ====================

    def _get_temperature(self) -> int:
        """Get CPU temperature in Celsius."""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                return int(f.read().strip()) // 1000
        except (FileNotFoundError, PermissionError):
            return 0

    # ==================== Context Manager ====================

    async def __aenter__(self) -> SwarmBridge:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()

