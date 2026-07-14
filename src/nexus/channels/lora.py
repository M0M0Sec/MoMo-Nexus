"""
LoRa Channel via Meshtastic.

Provides long-range, low-power communication using Meshtastic-compatible devices.
Supports Heltec, T-Beam, RAK, and other ESP32-based LoRa boards.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from nexus.channels.base import BaseChannel, ConnectionError, SendError
from nexus.domain.enums import ChannelStatus, ChannelType
from nexus.domain.models import Message

logger = logging.getLogger(__name__)

# Meshtastic import (optional dependency)
try:
    import meshtastic
    import meshtastic.serial_interface
    import meshtastic.tcp_interface
    from pubsub import pub

    MESHTASTIC_AVAILABLE = True
except ImportError:
    MESHTASTIC_AVAILABLE = False
    meshtastic = None  # type: ignore


class LoRaChannel(BaseChannel):
    """
    LoRa channel using Meshtastic protocol.

    Supports:
    - Serial connection (USB)
    - TCP connection (WiFi-enabled devices)
    - Message sending/receiving
    - Node discovery
    - Mesh routing (handled by Meshtastic)

    Configuration:
        serial_port: Serial port (e.g., /dev/ttyUSB0, COM3)
        tcp_host: TCP host for WiFi connection
        channel_name: Meshtastic channel name
        psk: Pre-shared key (base64)
    """

    # LoRa constraints
    MAX_PAYLOAD_SIZE = 200  # bytes
    DEFAULT_TIMEOUT = 30.0  # seconds
    DUTY_CYCLE_LIMIT = 0.01  # 1% for EU868

    def __init__(
        self,
        serial_port: str | None = None,
        tcp_host: str | None = None,
        channel_name: str = "MoMo-Ops",
        psk: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            channel_type=ChannelType.LORA,
            name="lora",
            config=config or {},
        )

        if not MESHTASTIC_AVAILABLE:
            logger.warning("Meshtastic library not installed. Install with: pip install meshtastic")

        self._serial_port = serial_port
        self._tcp_host = tcp_host
        self._channel_name = channel_name
        self._psk = psk

        self._interface: Any = None
        self._node_id: str | None = None
        self._nodes: dict[str, dict] = {}  # node_id -> node_info
        self._pending_messages: dict[str, asyncio.Future] = {}

        # Metrics
        self._metrics.latency_ms = 2000.0  # LoRa is slow
        self._metrics.bandwidth_kbps = 1.0  # ~1 kbps effective

        # Longer health check interval for LoRa
        self._health_check_interval = 60

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def node_id(self) -> str | None:
        """Get local node ID."""
        return self._node_id

    @property
    def nodes(self) -> dict[str, dict]:
        """Get discovered nodes."""
        return self._nodes.copy()

    # =========================================================================
    # Connection
    # =========================================================================

    async def _connect(self) -> None:
        """Connect to Meshtastic device."""
        if not MESHTASTIC_AVAILABLE:
            raise ConnectionError("Meshtastic library not installed")

        try:
            # Run blocking connection in thread pool
            loop = asyncio.get_event_loop()

            if self._serial_port:
                self._interface = await loop.run_in_executor(
                    None,
                    lambda: meshtastic.serial_interface.SerialInterface(self._serial_port),
                )
            elif self._tcp_host:
                self._interface = await loop.run_in_executor(
                    None,
                    lambda: meshtastic.tcp_interface.TCPInterface(self._tcp_host),
                )
            else:
                # Auto-detect serial port
                self._interface = await loop.run_in_executor(
                    None,
                    meshtastic.serial_interface.SerialInterface,
                )

            # Get local node info
            if self._interface.myInfo:
                self._node_id = f"!{self._interface.myInfo.my_node_num:08x}"
                logger.info(f"LoRa connected as node {self._node_id}")

            # Subscribe to messages
            pub.subscribe(self._on_meshtastic_receive, "meshtastic.receive")
            pub.subscribe(self._on_meshtastic_connection, "meshtastic.connection.established")
            pub.subscribe(self._on_meshtastic_node, "meshtastic.node.updated")

            # Initial node discovery
            await self._discover_nodes()

        except Exception as e:
            raise ConnectionError(f"Failed to connect to Meshtastic: {e}")

    async def _disconnect(self) -> None:
        """Disconnect from Meshtastic device."""
        try:
            # Unsubscribe from events
            try:
                pub.unsubscribe(self._on_meshtastic_receive, "meshtastic.receive")
                pub.unsubscribe(self._on_meshtastic_connection, "meshtastic.connection.established")
                pub.unsubscribe(self._on_meshtastic_node, "meshtastic.node.updated")
            except Exception:
                pass

            if self._interface:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._interface.close)
                self._interface = None

            self._node_id = None
            self._nodes.clear()

        except Exception as e:
            logger.warning(f"Error during LoRa disconnect: {e}")

    # =========================================================================
    # Sending
    # =========================================================================

    async def _send(self, message: Message) -> bool:
        """
        Send message via LoRa.

        Args:
            message: Message to send

        Returns:
            True if sent successfully
        """
        if not self._interface:
            raise SendError("Not connected to Meshtastic")

        # Serialize message
        payload = self._serialize_message(message)

        if len(payload) > self.MAX_PAYLOAD_SIZE:
            logger.warning(f"Message too large for LoRa: {len(payload)} > {self.MAX_PAYLOAD_SIZE}")
            # TODO: Implement fragmentation
            raise SendError(f"Message too large: {len(payload)} bytes")

        try:
            loop = asyncio.get_event_loop()

            # Determine destination
            destination = None
            if message.dst and message.dst != "broadcast":
                # Try to find node ID for destination
                destination = self._resolve_destination(message.dst)

            # Send via Meshtastic
            await loop.run_in_executor(
                None,
                lambda: self._interface.sendData(
                    payload,
                    destinationId=destination,
                    portNum=256,  # Private app port
                    wantAck=message.ack_required,
                    wantResponse=False,
                ),
            )

            logger.debug(f"LoRa sent message {message.id} ({len(payload)} bytes)")
            return True

        except Exception as e:
            logger.error(f"LoRa send failed: {e}")
            raise SendError(f"LoRa send failed: {e}")

    def _serialize_message(self, message: Message) -> bytes:
        """
        Serialize message for LoRa transmission.

        Uses compact JSON format to minimize size.
        """
        # Compact format for LoRa
        compact = {
            "v": message.v,
            # Full ID (12-char uuid hex). Truncating to 8 broke ACK correlation and
            # raised collision odds; the 4 extra bytes are negligible for LoRa.
            "id": message.id,
            "s": message.src,
            "t": message.type if isinstance(message.type, str) else message.type.value,
            "p": message.pri if isinstance(message.pri, str) else message.pri.value,
            "d": message.data,
        }

        if message.dst:
            compact["dst"] = message.dst

        if message.ack_required:
            compact["ack"] = 1

        # Minimal JSON
        return json.dumps(compact, separators=(",", ":")).encode("utf-8")

    def _deserialize_message(self, payload: bytes, sender: str | None = None) -> Message:
        """Deserialize received LoRa message."""
        try:
            data = json.loads(payload.decode("utf-8"))

            return Message(
                v=data.get("v", 1),
                id=data.get("id", ""),
                src=data.get("s", sender or "unknown"),
                dst=data.get("dst"),
                type=data.get("t", "data"),
                pri=data.get("p", "normal"),
                ack_required=bool(data.get("ack", False)),
                data=data.get("d", {}),
            )
        except Exception as e:
            logger.error(f"Failed to deserialize LoRa message: {e}")
            raise

    def _resolve_destination(self, device_id: str) -> str | None:
        """Resolve device ID to Meshtastic node ID."""
        # Check if it's already a node ID
        if device_id.startswith("!"):
            return device_id

        # Look up in known nodes
        for node_id, info in self._nodes.items():
            if info.get("user", {}).get("id") == device_id:
                return node_id

        # Broadcast if not found
        return None

    # =========================================================================
    # Receiving
    # =========================================================================

    def _on_meshtastic_receive(self, packet: dict, interface: Any) -> None:
        """Handle incoming Meshtastic packet."""
        try:
            # Check if it's a data packet for us
            if packet.get("decoded", {}).get("portnum") == "PRIVATE_APP":
                payload = packet["decoded"].get("payload")
                if payload:
                    sender = packet.get("fromId")
                    message = self._deserialize_message(payload, sender)

                    # Update metrics
                    self._metrics.messages_received += 1
                    self._metrics.bytes_received += len(payload)

                    # Trigger handlers
                    asyncio.create_task(self._on_message(message))

        except Exception as e:
            logger.error(f"Error processing LoRa packet: {e}")

    def _on_meshtastic_connection(self, interface: Any, topic: Any = None) -> None:
        """Handle Meshtastic connection events."""
        logger.info("Meshtastic connection established")
        self._status = ChannelStatus.UP
        self._consecutive_failures = 0

    def _on_meshtastic_node(self, node: dict, interface: Any = None) -> None:
        """Handle node discovery/update."""
        node_id = node.get("num")
        if node_id:
            node_id_str = f"!{node_id:08x}"
            self._nodes[node_id_str] = node
            logger.debug(f"Node updated: {node_id_str}")

    # =========================================================================
    # Node Discovery
    # =========================================================================

    async def _discover_nodes(self) -> None:
        """Discover nodes in the mesh."""
        if not self._interface:
            return

        try:
            loop = asyncio.get_event_loop()
            nodes = await loop.run_in_executor(
                None,
                lambda: self._interface.nodes if hasattr(self._interface, "nodes") else {},
            )

            for node_id, node_info in nodes.items():
                self._nodes[node_id] = node_info

            logger.info(f"Discovered {len(self._nodes)} LoRa nodes")

        except Exception as e:
            logger.warning(f"Node discovery failed: {e}")

    async def get_node_info(self, node_id: str) -> dict | None:
        """Get info for a specific node."""
        return self._nodes.get(node_id)

    # =========================================================================
    # Health Check
    # =========================================================================

    async def _health_check(self) -> bool:
        """Check LoRa channel health."""
        if not self._interface:
            return False

        try:
            # Check if interface is still valid
            loop = asyncio.get_event_loop()

            # Try to get node info (lightweight operation)
            info = await loop.run_in_executor(
                None,
                lambda: self._interface.myInfo if hasattr(self._interface, "myInfo") else None,
            )

            return info is not None

        except Exception as e:
            logger.warning(f"LoRa health check failed: {e}")
            return False

    # =========================================================================
    # Utilities
    # =========================================================================

    def get_signal_quality(self, node_id: str) -> dict | None:
        """Get signal quality for a node."""
        node = self._nodes.get(node_id)
        if node:
            return {
                "snr": node.get("snr"),
                "rssi": node.get("rssi"),
                "hops_away": node.get("hopsAway"),
            }
        return None

    async def send_broadcast(self, message: Message) -> bool:
        """Send broadcast message to all nodes."""
        message.dst = None  # Broadcast
        return await self.send(message)

