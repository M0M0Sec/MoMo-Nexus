"""
WiFi Channel.

Provides local network communication via WiFi.
Supports client mode, AP mode, and direct peer communication.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any

from nexus.channels.base import BaseChannel, ConnectionError, SendError
from nexus.domain.enums import ChannelType
from nexus.domain.models import Message

logger = logging.getLogger(__name__)

# aiohttp import (optional)
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None  # type: ignore


class WiFiMode(str, Enum):
    """WiFi operation mode."""

    CLIENT = "client"  # Connect to existing network
    AP = "ap"  # Create access point
    BOTH = "both"  # Simultaneous AP + client


@dataclass
class WiFiStatus:
    """WiFi connection status."""

    connected: bool
    ssid: str | None
    ip_address: str | None
    signal_strength: int | None  # dBm
    channel: int | None


class WiFiChannel(BaseChannel):
    """
    WiFi channel for local network communication.

    Supports:
    - HTTP/HTTPS communication
    - WebSocket connections
    - mDNS discovery
    - Direct TCP/UDP

    Configuration:
        mode: WiFi mode (client, ap, both)
        ssid: Network SSID (for client mode)
        api_endpoint: HTTP endpoint for message relay
        listen_port: Port for incoming connections (AP mode)
    """

    DEFAULT_PORT = 8765
    HTTP_TIMEOUT = 10.0

    def __init__(
        self,
        mode: WiFiMode = WiFiMode.CLIENT,
        ssid: str | None = None,
        password: str | None = None,
        api_endpoint: str | None = None,
        listen_port: int = DEFAULT_PORT,
        interface: str = "wlan0",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            channel_type=ChannelType.WIFI,
            name="wifi",
            config=config or {},
        )

        if not AIOHTTP_AVAILABLE:
            logger.warning("aiohttp not installed. Install with: pip install aiohttp")

        self._mode = mode
        self._ssid = ssid
        self._password = password
        self._api_endpoint = api_endpoint
        self._listen_port = listen_port
        self._interface = interface

        self._session: aiohttp.ClientSession | None = None
        self._server: asyncio.Server | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._ws_receive_task: asyncio.Task | None = None  # tracked receive loop
        self._status = WiFiStatus(
            connected=False,
            ssid=None,
            ip_address=None,
            signal_strength=None,
            channel=None,
        )

        # Peers discovered via mDNS
        self._peers: dict[str, str] = {}  # device_id -> ip:port

        # WiFi is fast
        self._metrics.latency_ms = 20.0
        self._metrics.bandwidth_kbps = 10000.0  # ~10 Mbps

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def wifi_status(self) -> WiFiStatus:
        """Get WiFi connection status."""
        return self._status

    @property
    def mode(self) -> WiFiMode:
        """Get WiFi mode."""
        return self._mode

    @property
    def peers(self) -> dict[str, str]:
        """Get discovered peers."""
        return self._peers.copy()

    # =========================================================================
    # Connection
    # =========================================================================

    async def _connect(self) -> None:
        """Connect WiFi channel."""
        try:
            # Check current WiFi status
            await self._check_wifi_status()

            if not self._status.connected:
                # Try to connect to configured network
                if self._ssid:
                    await self._connect_to_network()

            # Create HTTP session
            if AIOHTTP_AVAILABLE:
                timeout = aiohttp.ClientTimeout(total=self.HTTP_TIMEOUT)
                self._session = aiohttp.ClientSession(timeout=timeout)

            # Start server if in AP mode
            if self._mode in (WiFiMode.AP, WiFiMode.BOTH):
                await self._start_server()

            # Connect WebSocket if endpoint configured
            if self._api_endpoint and self._api_endpoint.startswith("ws"):
                await self._connect_websocket()

            # Start mDNS discovery
            await self._start_mdns()

            logger.info(f"WiFi channel connected (mode={self._mode.value})")

        except Exception as e:
            if self._session:
                await self._session.close()
                self._session = None
            raise ConnectionError(f"WiFi connection failed: {e}")

    def _cancel_ws_receive_task(self) -> None:
        """Cancel the WebSocket receive-loop task if one is running."""
        if self._ws_receive_task and not self._ws_receive_task.done():
            self._ws_receive_task.cancel()
        self._ws_receive_task = None

    async def _disconnect(self) -> None:
        """Disconnect WiFi channel."""
        try:
            # Stop the receive loop before tearing down the socket.
            self._cancel_ws_receive_task()

            # Close WebSocket
            if self._websocket and not self._websocket.closed:
                await self._websocket.close()
                self._websocket = None

            # Stop server
            if self._server:
                self._server.close()
                await self._server.wait_closed()
                self._server = None

            # Close HTTP session
            if self._session:
                await self._session.close()
                self._session = None

            self._peers.clear()
            logger.info("WiFi channel disconnected")

        except Exception as e:
            logger.warning(f"Error during WiFi disconnect: {e}")

    async def _check_wifi_status(self) -> None:
        """Check current WiFi connection status."""
        try:
            # Get local IP
            ip = await self._get_local_ip()
            if ip:
                self._status.connected = True
                self._status.ip_address = ip

            # Try to get SSID (Linux)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "iwgetid",
                    "-r",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await proc.communicate()
                if stdout:
                    self._status.ssid = stdout.decode().strip()
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"WiFi status check failed: {e}")

    async def _get_local_ip(self) -> str | None:
        """Get local IP address."""
        try:
            # Create UDP socket to determine local IP
            loop = asyncio.get_event_loop()

            def get_ip():
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    s.connect(("8.8.8.8", 80))
                    return s.getsockname()[0]
                except Exception:
                    return None
                finally:
                    s.close()

            return await loop.run_in_executor(None, get_ip)
        except Exception:
            return None

    async def _connect_to_network(self) -> None:
        """Connect to WiFi network (Linux)."""
        if not self._ssid:
            return

        try:
            # Use nmcli for connection
            proc = await asyncio.create_subprocess_exec(
                "nmcli",
                "device",
                "wifi",
                "connect",
                self._ssid,
                "password",
                self._password or "",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                logger.info(f"Connected to WiFi: {self._ssid}")
                self._status.connected = True
                self._status.ssid = self._ssid
            else:
                logger.warning(f"WiFi connection failed: {stderr.decode()}")

        except FileNotFoundError:
            logger.warning("nmcli not found, skipping WiFi connection")
        except Exception as e:
            logger.warning(f"WiFi connection failed: {e}")

    async def _start_server(self) -> None:
        """Start TCP server for incoming connections."""
        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                "0.0.0.0",
                self._listen_port,
            )
            logger.info(f"WiFi server listening on port {self._listen_port}")
        except Exception as e:
            logger.warning(f"Failed to start WiFi server: {e}")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming client connection."""
        addr = writer.get_extra_info("peername")
        logger.debug(f"WiFi client connected: {addr}")

        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break

                try:
                    message = Message.model_validate_json(data)
                    await self._on_message(message)

                    # Send ACK
                    response = {"status": "ok", "id": message.id}
                    writer.write(json.dumps(response).encode())
                    await writer.drain()

                except Exception as e:
                    logger.error(f"Error processing WiFi message: {e}")
                    writer.write(json.dumps({"status": "error"}).encode())
                    await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"WiFi client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _connect_websocket(self) -> None:
        """Connect to WebSocket endpoint."""
        if not self._session or not self._api_endpoint:
            return

        try:
            self._websocket = await self._session.ws_connect(self._api_endpoint)
            logger.info(f"WebSocket connected: {self._api_endpoint}")

            # Start receive loop, cancelling any previous one so reconnects (driven by
            # the health check) don't spawn a growing pile of receive tasks.
            self._cancel_ws_receive_task()
            self._ws_receive_task = asyncio.create_task(self._websocket_receive_loop())

        except Exception as e:
            logger.warning(f"WebSocket connection failed: {e}")
            self._websocket = None

    async def _websocket_receive_loop(self) -> None:
        """Receive messages from WebSocket."""
        if not self._websocket:
            return

        try:
            async for msg in self._websocket:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        message = Message.model_validate_json(msg.data)
                        self._metrics.messages_received += 1
                        await self._on_message(message)
                    except Exception as e:
                        logger.error(f"Error processing WebSocket message: {e}")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self._websocket.exception()}")
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"WebSocket receive error: {e}")

    async def _start_mdns(self) -> None:
        """Start mDNS service discovery."""
        # TODO: Implement mDNS discovery using zeroconf
        pass

    # =========================================================================
    # Sending
    # =========================================================================

    async def _send(self, message: Message) -> bool:
        """
        Send message via WiFi.

        Tries in order:
        1. WebSocket (if connected)
        2. Direct TCP to peer (if known)
        3. HTTP POST to endpoint
        """
        # Try WebSocket first
        if self._websocket and not self._websocket.closed:
            try:
                await self._websocket.send_json(message.model_dump(mode="json"))
                logger.debug(f"WiFi sent via WebSocket: {message.id}")
                return True
            except Exception as e:
                logger.warning(f"WebSocket send failed: {e}")

        # Try direct peer connection
        if message.dst and message.dst in self._peers:
            success = await self._send_to_peer(message)
            if success:
                return True

        # Fall back to HTTP
        if self._api_endpoint and not self._api_endpoint.startswith("ws"):
            return await self._http_post(message)

        raise SendError("No WiFi send method available")

    async def _send_to_peer(self, message: Message) -> bool:
        """Send message directly to peer via TCP."""
        if not message.dst or message.dst not in self._peers:
            return False

        peer_addr = self._peers[message.dst]
        try:
            host, port = peer_addr.split(":")
            port = int(port)

            reader, writer = await asyncio.open_connection(host, port)

            try:
                data = message.model_dump_json().encode()
                writer.write(data)
                await writer.drain()

                # Wait for ACK
                response = await asyncio.wait_for(reader.read(1024), timeout=5.0)
                result = json.loads(response.decode())

                logger.debug(f"WiFi sent to peer {message.dst}: {message.id}")
                return result.get("status") == "ok"

            finally:
                writer.close()
                await writer.wait_closed()

        except Exception as e:
            logger.warning(f"Peer send failed: {e}")
            return False

    async def _http_post(self, message: Message) -> bool:
        """Send message via HTTP POST."""
        if not self._session or not self._api_endpoint:
            return False

        try:
            async with self._session.post(
                self._api_endpoint,
                json=message.model_dump(mode="json"),
            ) as response:
                success = response.status < 400
                if success:
                    logger.debug(f"WiFi sent via HTTP: {message.id}")
                return success

        except Exception as e:
            logger.error(f"HTTP POST failed: {e}")
            return False

    # =========================================================================
    # Health Check
    # =========================================================================

    async def _health_check(self) -> bool:
        """Check WiFi channel health."""
        try:
            # Check if we have an IP
            ip = await self._get_local_ip()
            if not ip:
                return False

            # Check WebSocket if configured
            if self._websocket and self._websocket.closed:
                # Try to reconnect
                await self._connect_websocket()

            # Ping API endpoint if configured
            if self._api_endpoint and self._session:
                try:
                    async with self._session.get(
                        self._api_endpoint.replace("/api/", "/health"),
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as response:
                        return response.status < 500
                except Exception:
                    pass

            return True

        except Exception as e:
            logger.warning(f"WiFi health check failed: {e}")
            return False

    # =========================================================================
    # Utilities
    # =========================================================================

    def register_peer(self, device_id: str, address: str) -> None:
        """Register a peer for direct communication."""
        self._peers[device_id] = address
        logger.debug(f"Registered WiFi peer: {device_id} at {address}")

    def unregister_peer(self, device_id: str) -> None:
        """Unregister a peer."""
        self._peers.pop(device_id, None)

    async def scan_networks(self) -> list[dict]:
        """Scan for available WiFi networks."""
        networks = []

        try:
            proc = await asyncio.create_subprocess_exec(
                "nmcli",
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()

            for line in stdout.decode().strip().split("\n"):
                parts = line.split(":")
                if len(parts) >= 3:
                    networks.append({
                        "ssid": parts[0],
                        "signal": int(parts[1]) if parts[1] else 0,
                        "security": parts[2],
                    })

        except Exception as e:
            logger.warning(f"WiFi scan failed: {e}")

        return networks

