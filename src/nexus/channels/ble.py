"""
BLE Channel.

Provides short-range, low-power communication via Bluetooth Low Energy.
Uses GATT protocol for reliable data transfer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from nexus.channels.base import BaseChannel, ConnectionError, SendError
from nexus.domain.enums import ChannelType
from nexus.domain.models import Message

logger = logging.getLogger(__name__)

# bleak import (optional)
try:
    from bleak import BleakClient, BleakScanner

    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False
    BleakClient = None  # type: ignore
    BleakScanner = None  # type: ignore


# Nordic UART Service UUIDs (commonly used for BLE serial)
UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Write to device
UART_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # Receive from device


@dataclass
class BLEDevice:
    """Discovered BLE device."""

    address: str
    name: str | None
    rssi: int
    device_id: str | None = None
    connected: bool = False


class BLEChannel(BaseChannel):
    """
    BLE channel using GATT protocol.

    Supports:
    - Device scanning
    - Connection management
    - Nordic UART Service (NUS)
    - Multiple simultaneous connections

    Configuration:
        adapter: Bluetooth adapter (e.g., hci0)
        service_uuid: Custom GATT service UUID
        auto_connect: Auto-connect to known devices
    """

    MAX_PAYLOAD_SIZE = 512  # BLE MTU limit
    MAX_RX_BUFFER = 65536  # cap per-device reassembly buffer (drop garbage streams)
    SCAN_TIMEOUT = 10.0
    CONNECTION_TIMEOUT = 10.0

    def __init__(
        self,
        adapter: str = "hci0",
        service_uuid: str = UART_SERVICE_UUID,
        rx_uuid: str = UART_RX_CHAR_UUID,
        tx_uuid: str = UART_TX_CHAR_UUID,
        auto_connect: bool = True,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            channel_type=ChannelType.BLE,
            name="ble",
            config=config or {},
        )

        if not BLEAK_AVAILABLE:
            logger.warning("bleak not installed. Install with: pip install bleak")

        self._adapter = adapter
        self._service_uuid = service_uuid
        self._rx_uuid = rx_uuid
        self._tx_uuid = tx_uuid
        self._auto_connect = auto_connect

        # Connected devices: address -> BleakClient
        self._connections: dict[str, Any] = {}

        # Device registry: device_id -> BLEDevice
        self._devices: dict[str, BLEDevice] = {}

        # Reverse mapping: address -> device_id
        self._address_to_device: dict[str, str] = {}

        # Receive buffer: address -> accumulated data
        self._rx_buffer: dict[str, bytes] = {}

        # BLE characteristics
        self._metrics.latency_ms = 50.0
        self._metrics.bandwidth_kbps = 100.0

        # More frequent health checks for BLE
        self._health_check_interval = 30

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def connected_devices(self) -> list[str]:
        """Get list of connected device IDs."""
        return list(self._address_to_device.values())

    @property
    def discovered_devices(self) -> dict[str, BLEDevice]:
        """Get discovered devices."""
        return self._devices.copy()

    # =========================================================================
    # Connection
    # =========================================================================

    async def _connect(self) -> None:
        """Initialize BLE channel."""
        if not BLEAK_AVAILABLE:
            raise ConnectionError("bleak library not installed")

        try:
            # Scan for devices
            await self.scan()

            # Auto-connect to known devices
            if self._auto_connect:
                for _device_id, device in self._devices.items():
                    if device.name and "momo" in device.name.lower():
                        try:
                            await self.connect_device(device.address)
                        except Exception as e:
                            logger.warning(f"Auto-connect failed for {device.address}: {e}")

            logger.info(f"BLE channel initialized, {len(self._connections)} connections")

        except Exception as e:
            raise ConnectionError(f"BLE initialization failed: {e}")

    async def _disconnect(self) -> None:
        """Disconnect all BLE devices."""
        # Disconnect all clients
        for address in list(self._connections.keys()):
            await self.disconnect_device(address)

        self._devices.clear()
        self._address_to_device.clear()
        self._rx_buffer.clear()

        logger.info("BLE channel disconnected")

    async def scan(self, timeout: float = SCAN_TIMEOUT) -> list[BLEDevice]:
        """
        Scan for BLE devices.

        Args:
            timeout: Scan timeout in seconds

        Returns:
            List of discovered devices
        """
        if not BLEAK_AVAILABLE:
            return []

        discovered = []

        try:
            logger.info(f"Scanning for BLE devices ({timeout}s)...")

            devices = await BleakScanner.discover(
                timeout=timeout,
                return_adv=True,
            )

            for device, adv_data in devices.values():
                ble_device = BLEDevice(
                    address=device.address,
                    name=device.name or adv_data.local_name,
                    rssi=adv_data.rssi or -100,
                )

                # Check if device advertises our service
                if self._service_uuid.lower() in [
                    str(uuid).lower() for uuid in (adv_data.service_uuids or [])
                ]:
                    # Assign device ID from name or address
                    if device.name:
                        ble_device.device_id = device.name.lower().replace(" ", "-")
                    else:
                        ble_device.device_id = f"ble-{device.address.replace(':', '')[-6:]}"

                    self._devices[ble_device.device_id] = ble_device

                discovered.append(ble_device)

            logger.info(f"Found {len(discovered)} BLE devices, {len(self._devices)} compatible")

        except Exception as e:
            logger.error(f"BLE scan failed: {e}")

        return discovered

    async def connect_device(self, address: str) -> bool:
        """
        Connect to a BLE device.

        Args:
            address: Device MAC address

        Returns:
            True if connected successfully
        """
        if not BLEAK_AVAILABLE:
            return False

        if address in self._connections:
            logger.debug(f"Already connected to {address}")
            return True

        try:
            logger.info(f"Connecting to BLE device {address}...")

            client = BleakClient(address, timeout=self.CONNECTION_TIMEOUT)
            await client.connect()

            if client.is_connected:
                self._connections[address] = client

                # Find device ID
                device_id = None
                for did, device in self._devices.items():
                    if device.address == address:
                        device_id = did
                        device.connected = True
                        break

                if device_id:
                    self._address_to_device[address] = device_id

                # Subscribe to notifications
                await self._subscribe_notifications(client)

                logger.info(f"Connected to BLE device {address}")
                return True

            return False

        except Exception as e:
            logger.error(f"BLE connection failed: {e}")
            return False

    async def disconnect_device(self, address: str) -> None:
        """Disconnect from a BLE device."""
        if address in self._connections:
            try:
                client = self._connections[address]
                if client.is_connected:
                    await client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting {address}: {e}")
            finally:
                del self._connections[address]
                self._address_to_device.pop(address, None)
                self._rx_buffer.pop(address, None)  # don't leak this device's buffer

                # Update device status
                for device in self._devices.values():
                    if device.address == address:
                        device.connected = False
                        break

                logger.info(f"Disconnected from {address}")

    async def _subscribe_notifications(self, client: Any) -> None:
        """Subscribe to TX characteristic notifications."""
        try:
            # Find TX characteristic
            for service in client.services:
                if service.uuid.lower() == self._service_uuid.lower():
                    for char in service.characteristics:
                        if char.uuid.lower() == self._tx_uuid.lower():
                            await client.start_notify(
                                char.uuid,
                                lambda sender, data: asyncio.create_task(
                                    self._handle_notification(client.address, data)
                                ),
                            )
                            logger.debug(f"Subscribed to notifications on {client.address}")
                            return

        except Exception as e:
            logger.warning(f"Failed to subscribe to notifications: {e}")

    async def _handle_notification(self, address: str, data: bytes) -> None:
        """Handle incoming notification data."""
        # Accumulate data in buffer
        if address not in self._rx_buffer:
            self._rx_buffer[address] = b""

        self._rx_buffer[address] += data

        # Cap the buffer: a partial stream with no delimiter must not grow without bound
        # (malformed/hostile peer). Drop the garbage and keep going.
        if len(self._rx_buffer[address]) > self.MAX_RX_BUFFER:
            logger.warning(
                "BLE rx buffer overflow for %s (%d bytes) — discarding",
                address, len(self._rx_buffer[address]),
            )
            self._rx_buffer[address] = b""
            return

        # Try to parse complete messages (newline-delimited JSON)
        while b"\n" in self._rx_buffer[address]:
            line, rest = self._rx_buffer[address].split(b"\n", 1)
            self._rx_buffer[address] = rest

            try:
                message = Message.model_validate_json(line)

                # Set source from device mapping if not specified
                if not message.src or message.src == "unknown":
                    device_id = self._address_to_device.get(address)
                    if device_id:
                        message.src = device_id

                self._metrics.messages_received += 1
                self._metrics.bytes_received += len(line)

                await self._on_message(message)

            except Exception as e:
                logger.error(f"Failed to parse BLE message: {e}")

    # =========================================================================
    # Sending
    # =========================================================================

    async def _send(self, message: Message) -> bool:
        """
        Send message via BLE.

        Args:
            message: Message to send

        Returns:
            True if sent successfully
        """
        if not self._connections:
            raise SendError("No BLE devices connected")

        # Serialize message
        payload = message.model_dump_json().encode() + b"\n"

        if len(payload) > self.MAX_PAYLOAD_SIZE:
            raise SendError(f"Message too large for BLE: {len(payload)} bytes")

        # Determine target device
        target_addresses = []

        if message.dst:
            # Find specific device
            for address, device_id in self._address_to_device.items():
                if device_id == message.dst:
                    target_addresses.append(address)
                    break

            if not target_addresses:
                raise SendError(f"Device not connected: {message.dst}")
        else:
            # Broadcast to all connected devices
            target_addresses = list(self._connections.keys())

        # Send to each target
        success = False
        for address in target_addresses:
            try:
                await self._send_to_device(address, payload)
                success = True
                logger.debug(f"BLE sent to {address}: {message.id}")
            except Exception as e:
                logger.warning(f"BLE send to {address} failed: {e}")

        return success

    async def _send_to_device(self, address: str, data: bytes) -> None:
        """Send data to a specific device."""
        client = self._connections.get(address)
        if not client or not client.is_connected:
            raise SendError(f"Device not connected: {address}")

        try:
            # Find RX characteristic
            for service in client.services:
                if service.uuid.lower() == self._service_uuid.lower():
                    for char in service.characteristics:
                        if char.uuid.lower() == self._rx_uuid.lower():
                            # Send in chunks if needed (BLE MTU)
                            mtu = 20  # Conservative default
                            for i in range(0, len(data), mtu):
                                chunk = data[i : i + mtu]
                                await client.write_gatt_char(char.uuid, chunk)
                                await asyncio.sleep(0.01)  # Small delay between chunks

                            self._metrics.messages_sent += 1
                            self._metrics.bytes_sent += len(data)
                            return

            raise SendError("RX characteristic not found")

        except Exception as e:
            raise SendError(f"BLE write failed: {e}")

    # =========================================================================
    # Health Check
    # =========================================================================

    async def _health_check(self) -> bool:
        """Check BLE channel health."""
        if not BLEAK_AVAILABLE:
            return False

        # Check if any devices are connected
        connected = 0
        for address, client in list(self._connections.items()):
            try:
                if client.is_connected:
                    connected += 1
                else:
                    # Remove stale connection
                    await self.disconnect_device(address)
            except Exception:
                await self.disconnect_device(address)

        # If we have no connections but devices are known, try to reconnect
        if connected == 0 and self._devices:
            logger.info("No BLE connections, attempting reconnect...")
            for device in self._devices.values():
                if not device.connected:
                    try:
                        await self.connect_device(device.address)
                        if device.connected:
                            connected += 1
                            break
                    except Exception:
                        pass

        return connected > 0

    # =========================================================================
    # Utilities
    # =========================================================================

    async def get_device_info(self, address: str) -> dict | None:
        """Get information about a connected device."""
        client = self._connections.get(address)
        if not client:
            return None

        try:
            info = {
                "address": address,
                "connected": client.is_connected,
                "mtu": client.mtu_size if hasattr(client, "mtu_size") else None,
                "services": [],
            }

            for service in client.services:
                service_info = {
                    "uuid": str(service.uuid),
                    "characteristics": [str(c.uuid) for c in service.characteristics],
                }
                info["services"].append(service_info)

            return info

        except Exception as e:
            logger.error(f"Failed to get device info: {e}")
            return None

