"""
Notification Manager.

Central manager for all notification channels (Ntfy, Discord, Telegram, etc.)
Integrates with AlertManager as a handler.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nexus.notifications.ntfy import NtfyClient, NtfyConfig

if TYPE_CHECKING:
    from nexus.fleet.alerts import Alert

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Manages notification channels and dispatches alerts.

    Usage:
        manager = NotificationManager()
        manager.configure_ntfy(NtfyConfig(
            enabled=True,
            server_url="https://ntfy.sh",
            topic="momo-alerts"
        ))

        # Register as alert handler
        alert_manager.add_handler(manager.handle_alert)

        # Or send directly
        await manager.notify(
            "Password cracked!",
            title="Success",
            severity="high"
        )
    """

    def __init__(self) -> None:
        self._ntfy: NtfyClient | None = None
        self._lock = asyncio.Lock()

    # =========================================================================
    # Configuration
    # =========================================================================

    def configure_ntfy(self, config: NtfyConfig) -> None:
        """Configure Ntfy.sh client."""
        if config.enabled:
            self._ntfy = NtfyClient(config)
            logger.info(f"Ntfy configured: {config.topic_url}")
        else:
            self._ntfy = None
            logger.info("Ntfy disabled")

    @property
    def ntfy_enabled(self) -> bool:
        """Check if Ntfy is enabled."""
        return self._ntfy is not None and self._ntfy.config.enabled

    # =========================================================================
    # Alert Handler (for AlertManager integration)
    # =========================================================================

    async def handle_alert(self, alert: Alert) -> None:
        """
        Handle alert from AlertManager.

        This method is designed to be registered as an AlertManager handler:
            alert_manager.add_handler(notification_manager.handle_alert)

        Args:
            alert: Alert to process
        """
        if not self._ntfy:
            return

        try:
            result = await self._ntfy.send_alert(
                alert_type=alert.type.value,
                severity=alert.severity.value,
                title=alert.title,
                message=alert.message,
                device_id=alert.device_id,
                data=alert.data,
            )

            if not result.success:
                logger.warning(f"Failed to send notification: {result.error}")

        except Exception as e:
            logger.error(f"Notification error: {e}")

    # =========================================================================
    # Direct Notification API
    # =========================================================================

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: str = "medium",
        tags: list[str] | None = None,
    ) -> bool:
        """
        Send a notification through all enabled channels.

        Args:
            message: Notification message
            title: Notification title
            severity: Severity level for priority mapping
            tags: Additional tags/emojis

        Returns:
            True if at least one channel succeeded
        """
        success = False

        if self._ntfy:
            priority_map = {
                "critical": "max",
                "high": "high",
                "medium": "default",
                "low": "low",
                "info": "min",
            }
            priority = priority_map.get(severity, "default")

            result = await self._ntfy.send(
                message=message,
                title=title,
                priority=priority,
                tags=tags,
            )
            success = success or result.success

        return success

    async def notify_handshake(
        self,
        ssid: str,
        bssid: str,
        device_id: str | None = None,
    ) -> bool:
        """Send handshake captured notification."""
        return await self.notify(
            message=f"Captured from {ssid} ({bssid})",
            title="🤝 Handshake Captured",
            severity="high",
            tags=["handshake", "wifi"],
        )

    async def notify_cracked(
        self,
        ssid: str,
        password: str,
        device_id: str | None = None,
    ) -> bool:
        """Send password cracked notification."""
        return await self.notify(
            message=f"SSID: {ssid}\nPassword: {password}",
            title="🔓 Password Cracked!",
            severity="critical",
            tags=["key", "tada"],
        )

    async def notify_credential(
        self,
        username: str,
        target: str,
        device_id: str | None = None,
    ) -> bool:
        """Send credential captured notification."""
        return await self.notify(
            message=f"User: {username}\nTarget: {target}",
            title="🎣 Credential Captured",
            severity="high",
            tags=["fishing_pole_and_fish", "lock"],
        )

    async def notify_device_offline(
        self,
        device_id: str,
        last_seen: str | None = None,
    ) -> bool:
        """Send device offline notification."""
        message = f"Device {device_id} went offline"
        if last_seen:
            message += f"\nLast seen: {last_seen}"

        return await self.notify(
            message=message,
            title="⚠️ Device Offline",
            severity="medium",
            tags=["warning", "satellite"],
        )

    # =========================================================================
    # Testing
    # =========================================================================

    async def test_ntfy(self) -> dict:
        """
        Test Ntfy connection.

        Returns:
            Dict with success status and details
        """
        if not self._ntfy:
            return {
                "success": False,
                "error": "Ntfy not configured",
                "enabled": False,
            }

        result = await self._ntfy.test()
        return {
            "success": result.success,
            "error": result.error,
            "message_id": result.message_id,
            "enabled": True,
            "server": self._ntfy.config.server_url,
            "topic": self._ntfy.config.topic,
        }

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def close(self) -> None:
        """Close all notification clients."""
        if self._ntfy:
            await self._ntfy.close()

