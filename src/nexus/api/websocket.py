"""
WebSocket support for real-time updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from nexus.core.events import Event, EventBus, get_event_bus

logger = logging.getLogger(__name__)

router = APIRouter()


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts.

    Features:
    - Connection management
    - Event subscription
    - Broadcast to all/filtered clients
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus or get_event_bus()
        self._connections: set[WebSocket] = set()
        self._subscriptions: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

        # Subscribe to all events for forwarding
        self._event_bus.subscribe_all(self._on_event)

    async def connect(self, websocket: WebSocket, subscriptions: list[str] | None = None) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()

        async with self._lock:
            self._connections.add(websocket)
            self._subscriptions[websocket] = set(subscriptions or ["*"])

        logger.info(f"WebSocket connected, total: {len(self._connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            self._connections.discard(websocket)
            self._subscriptions.pop(websocket, None)

        logger.info(f"WebSocket disconnected, total: {len(self._connections)}")

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast message to all connected clients."""
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        disconnected = []

        async with self._lock:
            connections = list(self._connections)
            subscriptions = dict(self._subscriptions)

        for ws in connections:
            # Check subscription filter
            ws_subs = subscriptions.get(ws, {"*"})
            if "*" not in ws_subs and event_type not in ws_subs:
                continue

            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"WebSocket send error: {e}")
                disconnected.append(ws)

        # Clean up disconnected
        for ws in disconnected:
            await self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, event_type: str, data: dict[str, Any]) -> None:
        """Send message to specific client."""
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        await websocket.send_json(message)

    async def _on_event(self, event: Event) -> None:
        """Handle internal event, forward to WebSocket clients."""
        await self.broadcast(event.type.value, event.data)

    @property
    def connection_count(self) -> int:
        """Get number of active connections."""
        return len(self._connections)


# Global WebSocket manager
_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    """Get or create WebSocket manager."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager


# =============================================================================
# WebSocket Endpoint
# =============================================================================


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: str | None = Query(None),
    events: str | None = Query(None, description="Comma-separated event types to subscribe"),
):
    """
    WebSocket endpoint for real-time updates.

    Query Parameters:
        api_key: API key for authentication
        events: Comma-separated list of event types to subscribe to

    Events:
        - message.received, message.sent, message.queued
        - device.online, device.offline, device.status
        - channel.up, channel.down
        - alert.new, alert.acked
        - * (all events)

    Messages:
        Incoming:
            {"type": "subscribe", "events": ["device.status", "alert.new"]}
            {"type": "ping"}

        Outgoing:
            {"type": "event_type", "data": {...}, "timestamp": "..."}
            {"type": "pong"}
    """
    # Verify API key if auth enabled
    config = websocket.app.state.config
    if config.server.auth_enabled:
        expected_key = websocket.app.state.api_key
        # SECURITY: constant-time comparison (matches HTTP auth); plain != leaks timing.
        if not api_key or not secrets.compare_digest(api_key, expected_key):
            await websocket.close(code=4001, reason="Invalid API key")
            return

    # Parse event subscriptions
    subscriptions = None
    if events:
        subscriptions = [e.strip() for e in events.split(",")]

    manager = get_ws_manager()
    await manager.connect(websocket, subscriptions)

    try:
        # Send welcome message
        await manager.send_to(websocket, "connected", {
            "message": "Connected to Nexus WebSocket",
            "subscriptions": subscriptions or ["*"],
        })

        # Message loop
        while True:
            try:
                data = await websocket.receive_json()

                msg_type = data.get("type", "")

                if msg_type == "ping":
                    await manager.send_to(websocket, "pong", {})

                elif msg_type == "subscribe":
                    # Update subscriptions
                    new_events = data.get("events", [])
                    async with manager._lock:
                        manager._subscriptions[websocket] = set(new_events)
                    await manager.send_to(websocket, "subscribed", {"events": new_events})

                elif msg_type == "unsubscribe":
                    # Clear subscriptions
                    async with manager._lock:
                        manager._subscriptions[websocket] = set()
                    await manager.send_to(websocket, "unsubscribed", {})

                else:
                    await manager.send_to(websocket, "error", {
                        "message": f"Unknown message type: {msg_type}",
                    })

            except json.JSONDecodeError:
                await manager.send_to(websocket, "error", {"message": "Invalid JSON"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket)

