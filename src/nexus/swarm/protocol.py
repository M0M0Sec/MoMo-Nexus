"""
MoMo-Swarm Protocol Implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Message formats and protocol handling for LoRa mesh communication.
Integrated from MoMo-Swarm into Nexus.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SwarmMessageType(str, Enum):
    """Swarm message type codes."""
    ALERT = "alert"      # Device → Operator: Event notification
    STATUS = "status"    # Device → Operator: Periodic heartbeat
    CMD = "cmd"          # Operator → Device: Command execution
    ACK = "ack"          # Any → Any: Acknowledgment
    GPS = "gps"          # Device → Operator: Location update
    DATA = "data"        # Device → Operator: Data exfiltration


class EventCode(str, Enum):
    """Alert event codes from field devices."""
    # WiFi Events
    HANDSHAKE_CAPTURED = "hs_cap"
    PMKID_CAPTURED = "pmkid"
    NEW_AP = "new_ap"
    NEW_CLIENT = "new_cl"
    PASSWORD_CRACKED = "cracked"

    # Attack Events
    EVIL_TWIN_CONNECT = "et_conn"
    EVIL_TWIN_CREDENTIAL = "et_cred"
    KARMA_CLIENT = "karma"
    EAP_CREDENTIAL = "eap"
    WPA3_EVENT = "wpa3"

    # BLE Events
    BLE_DEVICE = "ble_dev"
    BLE_CONNECT = "ble_conn"

    # GhostBridge Events
    GHOST_BEACON = "gh_beacon"
    GHOST_TUNNEL = "gh_tunnel"
    GHOST_EXFIL = "gh_exfil"

    # Mimic Events
    MIMIC_TRIGGER = "mm_trig"
    MIMIC_INJECT = "mm_inject"

    # System Events
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    LOW_BATTERY = "low_bat"
    ALERT = "alert"


class CommandCode(str, Enum):
    """Command codes sent to field devices."""
    # General
    STATUS = "status"
    PING = "ping"
    MODE = "mode"
    SHELL = "shell"
    POWER = "power"
    CONFIG = "config"

    # MoMo Commands
    DEAUTH = "deauth"
    EVIL_TWIN = "eviltwin"
    KARMA = "karma"
    CAPTURE = "capture"
    CRACK = "crack"
    SCAN = "scan"

    # GhostBridge Commands
    GHOST_START = "gh_start"
    GHOST_STOP = "gh_stop"
    GHOST_TUNNEL = "gh_tunnel"

    # Mimic Commands
    MIMIC_ARM = "mm_arm"
    MIMIC_DISARM = "mm_disarm"
    MIMIC_TRIGGER = "mm_trigger"


class AckStatus(str, Enum):
    """Acknowledgment status codes."""
    OK = "ok"
    ERROR = "error"
    BUSY = "busy"
    QUEUED = "queued"
    TIMEOUT = "timeout"


# Maximum message size for Meshtastic/LoRa
MAX_SWARM_MESSAGE_SIZE = 237


@dataclass
class SwarmMessage:
    """
    MoMo-Swarm message format.

    All messages follow this JSON structure for LoRa transmission.
    Designed for minimal size while maintaining protocol clarity.
    """

    type: SwarmMessageType
    source: str
    data: dict[str, Any]
    version: int = 1
    destination: str | None = None
    timestamp: int = field(default_factory=lambda: int(time.time()))
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (the wire shape, minus JSON encoding).

        Prefer this over to_json() when embedding a swarm message inside another
        structured payload, to avoid double JSON-encoding (escaped-string bloat).
        """
        msg: dict[str, Any] = {
            "v": self.version,
            "t": self.type.value if isinstance(self.type, SwarmMessageType) else self.type,
            "src": self.source,
            "ts": self.timestamp,
            "seq": self.sequence,
            "d": self.data,
        }
        if self.destination:
            msg["dst"] = self.destination
        return msg

    def to_json(self, compact: bool = True) -> str:
        """
        Serialize message to JSON string.

        Args:
            compact: Use compact JSON format (recommended for LoRa)

        Returns:
            JSON string representation
        """
        msg = self.to_dict()
        if compact:
            return json.dumps(msg, separators=(',', ':'))
        return json.dumps(msg)

    def to_bytes(self) -> bytes:
        """Serialize message to bytes for transmission."""
        return self.to_json(compact=True).encode('utf-8')

    @classmethod
    def from_dict(cls, data: Any) -> SwarmMessage | None:
        """Parse a message from an already-decoded dict (see to_dict). Returns None on
        any validation failure."""
        try:
            if not isinstance(data, dict):
                return None

            # Validate required fields
            required = ['v', 't', 'src', 'ts', 'seq', 'd']
            if not all(k in data for k in required):
                return None

            # Validate version
            if data['v'] != 1:
                return None

            # Parse message type. An unknown type is an unsupported/malformed message —
            # reject it (the ValueError is caught below → None) instead of storing a raw
            # string, which would later break `.type.value` accesses on the receive path.
            msg_type = SwarmMessageType(data['t'])

            return cls(
                version=data['v'],
                type=msg_type,
                source=data['src'],
                destination=data.get('dst'),
                timestamp=data['ts'],
                sequence=data['seq'],
                data=data['d']
            )
        except (KeyError, ValueError):
            return None

    @classmethod
    def from_json(cls, json_str: str) -> SwarmMessage | None:
        """
        Parse message from JSON string.

        Args:
            json_str: JSON string to parse

        Returns:
            SwarmMessage object or None if parsing fails
        """
        try:
            return cls.from_dict(json.loads(json_str))
        except (json.JSONDecodeError, ValueError):
            return None

    @classmethod
    def from_bytes(cls, data: bytes) -> SwarmMessage | None:
        """Parse message from bytes."""
        try:
            return cls.from_json(data.decode('utf-8'))
        except UnicodeDecodeError:
            return None

    def size(self) -> int:
        """Get serialized message size in bytes."""
        return len(self.to_bytes())

    def is_valid_size(self) -> bool:
        """Check if message fits within LoRa size limit."""
        return self.size() <= MAX_SWARM_MESSAGE_SIZE


class SwarmMessageBuilder:
    """
    Builder class for constructing MoMo-Swarm messages.

    Provides convenient methods for creating different message types
    with proper formatting and size management.
    """

    def __init__(self, device_id: str):
        """
        Initialize message builder.

        Args:
            device_id: This device's identifier (e.g., "momo-001", "nexus-hub")
        """
        self.device_id = device_id
        self._sequence = 0

    def _next_seq(self) -> int:
        """Get next sequence number (wraps at 65535)."""
        self._sequence = (self._sequence + 1) % 65536
        return self._sequence

    def alert(
        self,
        event: EventCode | str,
        data: dict[str, Any],
        destination: str | None = None
    ) -> SwarmMessage:
        """
        Create an alert message.

        Args:
            event: Event code (e.g., EventCode.HANDSHAKE_CAPTURED)
            data: Event-specific data
            destination: Optional destination device ID

        Returns:
            Alert message
        """
        return SwarmMessage(
            type=SwarmMessageType.ALERT,
            source=self.device_id,
            destination=destination,
            sequence=self._next_seq(),
            data={
                "evt": event.value if isinstance(event, EventCode) else event,
                **data
            }
        )

    def status(
        self,
        uptime: int,
        battery: int,
        temperature: int,
        gps: tuple[float, float],
        aps_seen: int = 0,
        handshakes: int = 0,
        detail: bool = False,
        **extra: Any
    ) -> SwarmMessage:
        """
        Create a status/heartbeat message.

        Args:
            uptime: Uptime in seconds
            battery: Battery percentage (0-100)
            temperature: CPU temperature in Celsius
            gps: (latitude, longitude) tuple
            aps_seen: Number of APs seen
            handshakes: Number of handshakes captured
            detail: Include detailed info
            **extra: Additional status fields

        Returns:
            Status message
        """
        data: dict[str, Any] = {
            "up": uptime,
            "bat": battery,
            "temp": temperature,
            "gps": list(gps),
            "aps": aps_seen,
            "hs": handshakes
        }

        if detail:
            data["detail"] = True

        data.update(extra)

        return SwarmMessage(
            type=SwarmMessageType.STATUS,
            source=self.device_id,
            sequence=self._next_seq(),
            data=data
        )

    def command(
        self,
        cmd: CommandCode | str,
        params: dict[str, Any],
        destination: str
    ) -> SwarmMessage:
        """
        Create a command message.

        Args:
            cmd: Command code
            params: Command parameters
            destination: Target device ID

        Returns:
            Command message
        """
        return SwarmMessage(
            type=SwarmMessageType.CMD,
            source=self.device_id,
            destination=destination,
            sequence=self._next_seq(),
            data={
                "cmd": cmd.value if isinstance(cmd, CommandCode) else cmd,
                **params
            }
        )

    def ack(
        self,
        ref_seq: int,
        status: AckStatus,
        destination: str,
        result: str | None = None,
        error: str | None = None
    ) -> SwarmMessage:
        """
        Create an acknowledgment message.

        Args:
            ref_seq: Sequence number of the message being acknowledged
            status: Ack status
            destination: Original sender's device ID
            result: Optional result data
            error: Optional error message

        Returns:
            Ack message
        """
        data: dict[str, Any] = {
            "ref": ref_seq,
            "status": status.value
        }

        if result:
            data["result"] = result[:200]  # Limit result size
        if error:
            data["error"] = error[:100]  # Limit error size

        return SwarmMessage(
            type=SwarmMessageType.ACK,
            source=self.device_id,
            destination=destination,
            sequence=self._next_seq(),
            data=data
        )

    def gps(
        self,
        lat: float,
        lon: float,
        alt: float = 0,
        speed: float = 0,
        hdop: float = 0,
        sats: int = 0
    ) -> SwarmMessage:
        """
        Create a GPS location message.

        Args:
            lat: Latitude
            lon: Longitude
            alt: Altitude in meters
            speed: Speed in m/s
            hdop: Horizontal dilution of precision
            sats: Number of satellites

        Returns:
            GPS message
        """
        return SwarmMessage(
            type=SwarmMessageType.GPS,
            source=self.device_id,
            sequence=self._next_seq(),
            data={
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "alt": int(alt),
                "speed": round(speed, 1),
                "hdop": round(hdop, 1),
                "sats": sats
            }
        )

    def data_chunk(
        self,
        chunk_id: str,
        name: str,
        chunk_num: int,
        total_chunks: int,
        data: str,
        destination: str
    ) -> SwarmMessage:
        """
        Create a data exfiltration chunk message.

        Args:
            chunk_id: Unique transfer ID
            name: File/data name
            chunk_num: Current chunk number (1-based)
            total_chunks: Total number of chunks
            data: Base64 encoded chunk data
            destination: Destination device ID

        Returns:
            Data message
        """
        return SwarmMessage(
            type=SwarmMessageType.DATA,
            source=self.device_id,
            destination=destination,
            sequence=self._next_seq(),
            data={
                "id": chunk_id,
                "name": name[:32],  # Limit filename
                "chunk": chunk_num,
                "total": total_chunks,
                "data": data
            }
        )


class SequenceTracker:
    """
    Track message sequence numbers to prevent replay attacks.

    Uses a sliding window approach to efficiently detect
    replay attempts while allowing for out-of-order delivery.
    """

    def __init__(self, window_size: int = 100, max_sources: int = 1000):
        """
        Initialize sequence tracker.

        Args:
            window_size: Size of sequence window for replay detection
            max_sources: Max distinct source IDs to track (LRU-evicted). Bounds memory
                against many devices or spoofed source IDs.
        """
        self.window_size = window_size
        self.max_sources = max_sources
        self._last_seq: dict[str, int] = {}
        # OrderedDict so the least-recently-used source can be evicted at the cap.
        self._seen: OrderedDict[str, list[int]] = OrderedDict()

    # 16-bit sequence space (matches the on-wire uint16 sequence field).
    _SEQ_SPACE = 65536

    @classmethod
    def _delta(cls, a: int, b: int) -> int:
        """Signed distance a-b in 16-bit sequence space, in [-32768, 32767].

        Wrap-aware: _delta(5, 65530) == 11 (5 is 11 ahead of 65530 after wrap).
        """
        d = (a - b) % cls._SEQ_SPACE
        if d >= cls._SEQ_SPACE // 2:
            d -= cls._SEQ_SPACE
        return d

    def is_valid(self, source: str, sequence: int) -> bool:
        """
        Check if a sequence number is valid (not a replay, not too old).

        Sliding-window semantics (as documented): accepts in-order and *out-of-order*
        messages within `window_size` of the highest seen sequence, rejects exact
        replays and sequences older than the window. Wrap-around (65535 → 0) is handled
        via modular distance.

        Returns:
            True if valid (first time seen, within window); False for replay / too old.
        """
        # Bound the number of tracked sources (LRU). Evict the oldest when a NEW source
        # would exceed the cap — protects against spoofed/one-off source IDs.
        if source not in self._seen and len(self._seen) >= self.max_sources:
            old_source, _ = self._seen.popitem(last=False)
            self._last_seq.pop(old_source, None)

        seen = self._seen.setdefault(source, [])
        self._seen.move_to_end(source)  # mark most-recently-used
        last = self._last_seq.get(source)

        # First message from this source.
        if last is None:
            self._last_seq[source] = sequence
            seen.append(sequence)
            return True

        # Exact replay of a recently-seen sequence.
        if sequence in seen:
            return False

        delta = self._delta(sequence, last)  # >0 ahead of window head, <0 behind

        if delta > 0:
            # Newer than the highest seen — advance the window head.
            self._last_seq[source] = sequence
        elif -delta > self.window_size:
            # Older than the window — cannot distinguish from a replay → reject.
            return False
        # else: older but within the window and not seen before → accept out-of-order
        # without moving the window head backwards.

        seen.append(sequence)
        if len(seen) > self.window_size:
            del seen[: -self.window_size]
        return True

    def reset(self, source: str | None = None) -> None:
        """
        Reset sequence tracking.

        Args:
            source: Specific source to reset, or None for all
        """
        if source:
            self._last_seq.pop(source, None)
            self._seen.pop(source, None)
        else:
            self._last_seq.clear()
            self._seen.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get tracking statistics."""
        return {
            "tracked_sources": len(self._last_seq),
            "sources": list(self._last_seq.keys()),
            "total_sequences": sum(len(v) for v in self._seen.values()),
        }

