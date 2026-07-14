"""
REST API Routes.

All API endpoints for Nexus.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from nexus._version import __version__
from nexus.api.auth import require_auth
from nexus.domain.enums import DeviceStatus, DeviceType, Priority

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================


class DeviceResponse(BaseModel):
    """Device response model."""

    id: str
    type: str
    name: str | None
    status: str
    last_seen: str | None
    battery: int | None
    version: str | None
    channels: list[str]
    location: dict | None


class MessageRequest(BaseModel):
    """Message send request."""

    dst: str = Field(..., description="Destination device ID")
    type: str = Field(default="data", description="Message type")
    priority: str = Field(default="normal", description="Priority level")
    data: dict = Field(default_factory=dict, description="Message payload")
    ack_required: bool = Field(default=False, description="Require acknowledgment")


class CommandRequest(BaseModel):
    """Command request."""

    device_id: str = Field(..., description="Target device ID")
    cmd: str = Field(..., description="Command name")
    params: dict = Field(default_factory=dict, description="Command parameters")
    timeout: int = Field(default=30, description="Timeout in seconds")
    wait: bool = Field(default=True, description="Wait for result")


class AlertResponse(BaseModel):
    """Alert response model."""

    id: str
    type: str
    severity: str
    title: str
    message: str
    device_id: str | None
    timestamp: str
    acknowledged: bool


class StatusResponse(BaseModel):
    """System status response."""

    status: str
    version: str
    uptime: int
    devices: dict
    channels: dict
    alerts: dict


# =============================================================================
# Helper Functions
# =============================================================================


def get_fleet_manager(request: Request):
    """Get fleet manager from app state."""
    manager = request.app.state.fleet_manager
    if not manager:
        raise HTTPException(status_code=503, detail="Fleet manager not initialized")
    return manager


def get_channel_manager(request: Request):
    """Get channel manager from app state."""
    manager = request.app.state.channel_manager
    if not manager:
        raise HTTPException(status_code=503, detail="Channel manager not initialized")
    return manager


def get_router(request: Request):
    """Get message router from app state."""
    router = request.app.state.router
    if not router:
        raise HTTPException(status_code=503, detail="Router not initialized")
    return router


# =============================================================================
# System Endpoints
# =============================================================================


@router.get("/status", response_model=StatusResponse, tags=["health"])
async def get_status(request: Request, _: str = require_auth):
    """
    Get system status.

    Returns current system status including:
    - Online/offline devices count
    - Channel availability
    - Active alerts
    - System uptime
    """
    fleet = request.app.state.fleet_manager
    channels = request.app.state.channel_manager

    return {
        "status": "running",
        "version": __version__,
        "uptime": 0,  # TODO: Track uptime
        "devices": await fleet.registry.get_stats() if fleet else {},
        "channels": channels.get_status() if channels else {},
        "alerts": await fleet.alerts.get_stats() if fleet else {},
    }


@router.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint.

    No authentication required. Use this endpoint for:
    - Load balancer health checks
    - Monitoring systems
    - Uptime verification

    Returns:
        status: "ok" if healthy
        version: Current API version
    """
    return {"status": "ok", "version": __version__}


@router.get("/stats", tags=["health"])
async def get_stats(request: Request, _: str = require_auth):
    """
    Get detailed system statistics.

    Returns aggregated stats including:
    - Total devices registered
    - Active connections per channel
    - Message throughput
    - Capture counts
    """
    fleet = request.app.state.fleet_manager
    if fleet:
        return await fleet.get_stats()
    return {}


# =============================================================================
# Device Endpoints
# =============================================================================


@router.get("/devices", response_model=list[DeviceResponse], tags=["devices"])
async def list_devices(
    request: Request,
    status: str | None = Query(None, description="Filter by status (online, offline, unknown)"),
    type: str | None = Query(None, description="Filter by device type (momo, ghostbridge, mimic, relay)"),
    _: str = require_auth,
):
    """
    List all registered devices.

    Returns a list of all devices registered with Nexus.
    Supports filtering by status and device type.

    Examples:
    - GET /devices?status=online - All online devices
    - GET /devices?type=momo - All MoMo field units
    """
    fleet = get_fleet_manager(request)

    if status:
        devices = await fleet.registry.get_by_status(DeviceStatus(status))
    elif type:
        devices = await fleet.registry.get_by_type(DeviceType(type))
    else:
        devices = await fleet.registry.get_all()

    return [
        DeviceResponse(
            id=d.id,
            type=d.type.value if hasattr(d.type, "value") else str(d.type),
            name=d.name,
            status=d.status.value if hasattr(d.status, "value") else str(d.status),
            last_seen=d.last_seen.isoformat() if d.last_seen else None,
            battery=d.battery,
            version=d.version,
            channels=[c.value if hasattr(c, "value") else str(c) for c in d.channels],
            location=d.location.model_dump() if d.location else None,
        )
        for d in devices
    ]


@router.get("/devices/{device_id}", response_model=DeviceResponse, tags=["devices"])
async def get_device(
    request: Request,
    device_id: str,
    _: str = require_auth,
):
    """
    Get device details.

    Returns detailed information about a specific device including:
    - Current status and last seen time
    - Battery level and version
    - Available communication channels
    - GPS location (if available)
    """
    fleet = get_fleet_manager(request)
    device = await fleet.registry.get(device_id)

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    return DeviceResponse(
        id=device.id,
        type=device.type.value if hasattr(device.type, "value") else str(device.type),
        name=device.name,
        status=device.status.value if hasattr(device.status, "value") else str(device.status),
        last_seen=device.last_seen.isoformat() if device.last_seen else None,
        battery=device.battery,
        version=device.version,
        channels=[c.value if hasattr(c, "value") else str(c) for c in device.channels],
        location=device.location.model_dump() if device.location else None,
    )


@router.get("/devices/{device_id}/health", tags=["devices"])
async def get_device_health(
    request: Request,
    device_id: str,
    _: str = require_auth,
):
    """
    Get device health information.

    Returns health metrics including:
    - Health score (0-100)
    - Heartbeat status
    - Resource usage (CPU, memory, battery)
    - Active issues/warnings
    """
    fleet = get_fleet_manager(request)
    health = await fleet.monitor.get_health(device_id)

    if not health:
        raise HTTPException(status_code=404, detail="Device health not found")

    return {
        "device_id": health.device_id,
        "health_score": health.health_score,
        "last_seen": health.last_seen.isoformat() if health.last_seen else None,
        "last_heartbeat": health.last_heartbeat.isoformat() if health.last_heartbeat else None,
        "consecutive_misses": health.consecutive_misses,
        "latency_ms": health.latency_ms,
        "battery": health.battery,
        "cpu": health.cpu,
        "memory": health.memory,
        "issues": health.issues,
    }


@router.delete("/devices/{device_id}", tags=["devices"])
async def unregister_device(
    request: Request,
    device_id: str,
    _: str = require_auth,
):
    """
    Unregister a device.

    Removes the device from Nexus fleet management.
    The device will need to re-register to reconnect.
    """
    fleet = get_fleet_manager(request)
    result = await fleet.registry.unregister(device_id)

    if not result:
        raise HTTPException(status_code=404, detail="Device not found")

    return {"status": "ok", "device_id": device_id}


# =============================================================================
# Command Endpoints
# =============================================================================


@router.post("/devices/{device_id}/command", tags=["messages"])
async def send_command(
    request: Request,
    device_id: str,
    cmd: str = Query(..., description="Command name (scan, capture, stop, reboot, etc.)"),
    params: str | None = Query(None, description="JSON params"),
    wait: bool = Query(True, description="Wait for result"),
    timeout: int = Query(30, description="Timeout seconds"),
    _: str = require_auth,
):
    """
    Send command to a device.

    Available commands depend on device type:

    **MoMo commands:**
    - `scan` - Start WiFi scanning
    - `capture` - Begin handshake capture
    - `stop` - Stop current operation
    - `reboot` - Restart device

    **GhostBridge commands:**
    - `beacon` - Send beacon
    - `stealth` - Toggle stealth mode

    **Mimic commands:**
    - `execute` - Run payload
    - `switch_mode` - Change USB mode
    """
    import json

    fleet = get_fleet_manager(request)

    # Parse params
    cmd_params = {}
    if params:
        try:
            cmd_params = json.loads(params)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid params JSON")

    result = await fleet.send_command(
        device_id=device_id,
        cmd=cmd,
        params=cmd_params,
        wait=wait,
        timeout=timeout,
    )

    return {
        "command_id": result.command_id,
        "device_id": result.device_id,
        "success": result.success,
        "pending": result.pending,
        "error": result.error,
        "data": result.data,
        "duration_ms": result.duration_ms,
    }


@router.post("/command")
async def send_command_body(
    request: Request,
    command: CommandRequest,
    _: str = require_auth,
):
    """Send command to a device (POST body)."""
    fleet = get_fleet_manager(request)

    result = await fleet.send_command(
        device_id=command.device_id,
        cmd=command.cmd,
        params=command.params,
        wait=command.wait,
        timeout=command.timeout,
    )

    return {
        "command_id": result.command_id,
        "device_id": result.device_id,
        "success": result.success,
        "pending": result.pending,
        "error": result.error,
        "data": result.data,
    }


@router.post("/broadcast")
async def broadcast_command(
    request: Request,
    cmd: str = Query(..., description="Command name"),
    device_type: str | None = Query(None, description="Filter by device type"),
    _: str = require_auth,
):
    """Broadcast command to multiple devices."""
    fleet = get_fleet_manager(request)

    results = await fleet.broadcast_command(
        cmd=cmd,
        device_type=device_type,
    )

    return {
        "command": cmd,
        "results": {
            device_id: {
                "success": r.success,
                "error": r.error,
            }
            for device_id, r in results.items()
        },
    }


# =============================================================================
# Message Endpoints
# =============================================================================


@router.post("/messages")
async def send_message(
    request: Request,
    message: MessageRequest,
    _: str = require_auth,
):
    """Send a message to a device."""
    from nexus.domain.enums import MessageType
    from nexus.domain.models import Message

    router = get_router(request)

    msg = Message(
        src="nexus",
        dst=message.dst,
        type=MessageType(message.type),
        pri=Priority(message.priority),
        ack_required=message.ack_required,
        data=message.data,
    )

    result = await router.route(msg)

    return {
        "message_id": msg.id,
        "success": result.success,
        "channel": result.channel.value if result.channel else None,
        "queued": result.queued,
        "error": result.error,
    }


# =============================================================================
# Alert Endpoints
# =============================================================================


@router.get("/alerts", response_model=list[AlertResponse])
async def list_alerts(
    request: Request,
    limit: int = Query(100, le=1000),
    unacknowledged: bool = Query(False),
    severity: str | None = Query(None),
    device_id: str | None = Query(None),
    _: str = require_auth,
):
    """List alerts."""
    from nexus.fleet.alerts import AlertSeverity

    fleet = get_fleet_manager(request)

    severity_filter = AlertSeverity(severity) if severity else None

    alerts = await fleet.alerts.get_all(
        limit=limit,
        unacknowledged_only=unacknowledged,
        severity=severity_filter,
        device_id=device_id,
    )

    return [
        AlertResponse(
            id=a.id,
            type=a.type.value,
            severity=a.severity.value,
            title=a.title,
            message=a.message,
            device_id=a.device_id,
            timestamp=a.timestamp.isoformat(),
            acknowledged=a.acknowledged,
        )
        for a in alerts
    ]


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(
    request: Request,
    alert_id: str,
    _: str = require_auth,
):
    """Get alert details."""
    fleet = get_fleet_manager(request)
    alert = await fleet.alerts.get(alert_id)

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return AlertResponse(
        id=alert.id,
        type=alert.type.value,
        severity=alert.severity.value,
        title=alert.title,
        message=alert.message,
        device_id=alert.device_id,
        timestamp=alert.timestamp.isoformat(),
        acknowledged=alert.acknowledged,
    )


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    request: Request,
    alert_id: str,
    _: str = require_auth,
):
    """Acknowledge an alert."""
    fleet = get_fleet_manager(request)
    result = await fleet.alerts.acknowledge(alert_id, "api")

    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")

    return {"status": "ok", "alert_id": alert_id}


@router.post("/alerts/ack-all")
async def acknowledge_all_alerts(
    request: Request,
    device_id: str | None = Query(None),
    severity: str | None = Query(None),
    _: str = require_auth,
):
    """Acknowledge all matching alerts."""
    from nexus.fleet.alerts import AlertSeverity

    fleet = get_fleet_manager(request)
    severity_filter = AlertSeverity(severity) if severity else None

    count = await fleet.alerts.acknowledge_all(
        device_id=device_id,
        severity=severity_filter,
        acknowledged_by="api",
    )

    return {"status": "ok", "acknowledged": count}


# =============================================================================
# Channel Endpoints
# =============================================================================


@router.get("/channels")
async def list_channels(request: Request, _: str = require_auth):
    """List all channels and their status."""
    channels = get_channel_manager(request)
    return channels.get_status()


@router.get("/channels/{channel_name}")
async def get_channel(
    request: Request,
    channel_name: str,
    _: str = require_auth,
):
    """Get channel details."""
    from nexus.domain.enums import ChannelType

    channels = get_channel_manager(request)

    try:
        channel_type = ChannelType(channel_name)
    except ValueError:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel = channels.get_channel(channel_type)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    return {
        "name": channel.name,
        "type": channel.channel_type.value,
        "status": channel.status.value,
        "connected": channel.is_connected,
        "available": channel.is_available(),
        "metrics": {
            "latency_ms": channel.metrics.latency_ms,
            "messages_sent": channel.metrics.messages_sent,
            "messages_received": channel.metrics.messages_received,
        },
    }


@router.post("/channels/{channel_name}/restart")
async def restart_channel(
    request: Request,
    channel_name: str,
    _: str = require_auth,
):
    """Restart a channel."""
    from nexus.domain.enums import ChannelType

    channels = get_channel_manager(request)

    try:
        channel_type = ChannelType(channel_name)
    except ValueError:
        raise HTTPException(status_code=404, detail="Channel not found")

    result = await channels.restart_channel(channel_type)

    return {"status": "ok" if result else "failed", "channel": channel_name}


# =============================================================================
# Dashboard Data
# =============================================================================


@router.get("/dashboard")
async def get_dashboard_data(request: Request, _: str = require_auth):
    """Get data for dashboard display."""
    fleet = request.app.state.fleet_manager
    if fleet:
        return await fleet.get_dashboard_data()
    return {}


# =============================================================================
# Notification Endpoints
# =============================================================================


class NotificationTestRequest(BaseModel):
    """Notification test request."""

    message: str = Field(default="Test notification from MoMo Nexus")
    title: str = Field(default="🧪 Test Notification")


class NtfyConfigUpdateRequest(BaseModel):
    """Ntfy configuration update request."""

    enabled: bool | None = None
    server_url: str | None = None
    topic: str | None = None
    access_token: str | None = None
    min_severity: str | None = None


def get_notification_manager(request: Request):
    """Get notification manager from app state."""
    manager = getattr(request.app.state, "notification_manager", None)
    if not manager:
        raise HTTPException(status_code=503, detail="Notification manager not initialized")
    return manager


@router.get("/notifications/status", tags=["notifications"])
async def get_notification_status(
    request: Request,
    _: str = require_auth,
):
    """
    Get notification system status.

    Returns the status of all notification channels:
    - Ntfy.sh: enabled, server URL, topic
    - Future: Telegram, Discord, etc.
    """
    manager = get_notification_manager(request)

    return {
        "ntfy": {
            "enabled": manager.ntfy_enabled,
            "server_url": manager._ntfy.config.server_url if manager._ntfy else None,
            "topic": manager._ntfy.config.topic if manager._ntfy else None,
            "min_severity": manager._ntfy.config.min_severity if manager._ntfy else None,
        },
    }


@router.post("/notifications/test", tags=["notifications"])
async def test_notification(
    request: Request,
    body: NotificationTestRequest | None = None,
    _: str = require_auth,
):
    """
    Send a test notification.

    Sends a test message through all enabled notification channels.
    Use this to verify your notification setup is working.

    Returns:
        success: Whether any notification was sent successfully
        channels: Status of each notification channel
    """
    manager = get_notification_manager(request)

    result = await manager.test_ntfy()

    return {
        "success": result.get("success", False),
        "channels": {
            "ntfy": result,
        },
    }


@router.post("/notifications/send", tags=["notifications"])
async def send_notification(
    request: Request,
    message: str = Query(..., description="Notification message"),
    title: str = Query(None, description="Notification title"),
    severity: str = Query("medium", description="Severity: critical, high, medium, low, info"),
    _: str = require_auth,
):
    """
    Send a custom notification.

    Manually trigger a notification through all enabled channels.

    Args:
        message: Notification body text
        title: Notification title (optional)
        severity: Severity level for priority mapping

    Returns:
        success: Whether notification was sent
    """
    manager = get_notification_manager(request)

    success = await manager.notify(
        message=message,
        title=title,
        severity=severity,
    )

    return {"success": success, "message": message}


@router.put("/notifications/ntfy/config", tags=["notifications"])
async def update_ntfy_config(
    request: Request,
    body: NtfyConfigUpdateRequest,
    _: str = require_auth,
):
    """
    Update Ntfy.sh configuration.

    Allows updating Ntfy settings without restarting:
    - Enable/disable notifications
    - Change server URL or topic
    - Update authentication
    - Adjust minimum severity filter
    """
    from nexus.notifications.ntfy import NtfyConfig as NtfyClientConfig

    manager = get_notification_manager(request)
    config = request.app.state.config

    # Update config
    if body.enabled is not None:
        config.notifications.ntfy.enabled = body.enabled
    if body.server_url is not None:
        config.notifications.ntfy.server_url = body.server_url
    if body.topic is not None:
        config.notifications.ntfy.topic = body.topic
    if body.access_token is not None:
        config.notifications.ntfy.access_token = body.access_token
    if body.min_severity is not None:
        config.notifications.ntfy.min_severity = body.min_severity

    # Reconfigure manager
    ntfy_config = NtfyClientConfig(
        enabled=config.notifications.ntfy.enabled,
        server_url=config.notifications.ntfy.server_url,
        topic=config.notifications.ntfy.topic,
        access_token=config.notifications.ntfy.access_token,
        min_severity=config.notifications.ntfy.min_severity,
    )
    manager.configure_ntfy(ntfy_config)

    return {
        "success": True,
        "config": {
            "enabled": config.notifications.ntfy.enabled,
            "server_url": config.notifications.ntfy.server_url,
            "topic": config.notifications.ntfy.topic,
            "min_severity": config.notifications.ntfy.min_severity,
        },
    }

